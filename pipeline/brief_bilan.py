#!/usr/bin/env python3
"""Bilan closing quotidien : UN seul message Telegram (HTML), envoyé le soir.

Contenu : jour par jour (aujourd'hui, hier, avant-hier), récap 3 et 7 derniers
jours, mois en cours (CA), calls à venir. Données closing (data.json) + ads
(ads.json, Meta par jour). Même règle de vente que les consoles : vente = OUI
closer OU virement Justine ; CA = prix confirmé sinon proposé. Show-up = OUI /
(OUI + NON), reprogrammés et annulés exclus. Qualifié = note closer >= 7/10.

Usage : python3 brief_bilan.py [--dry-run] [--refresh] [--date AAAA-MM-JJ]
  --refresh : lance refresh_data.py avant (pont Apps Script + Meta)
Config : telegram.json {"token", "chat_id"} ou env TELEGRAM_TOKEN / TELEGRAM_CHAT.
"""
import datetime as dt
import html
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from brief_telegram import is_sale, sale_amount, spend_range  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]
QUALIF_MIN = 7
TG_MAX = 4000  # limite Telegram 4096 caractères, marge pour les balises


# ---------- formats ----------
def e(n):
    return f"{round(n):,}".replace(",", " ") + " €"


def pct(num, den):
    return "·" if not den else f"{round(100 * num / den)} %"


def bpct(num, den):
    """Pourcentage en gras, ou un point discret s'il n'y a rien à calculer."""
    return b(pct(num, den)) if den else "·"


def ratio(num, den, unit="€"):
    return "·" if not den else e(num / den) if unit == "€" else f"{num / den:.1f}".replace(".", ",")


def cost_client(spend, ventes):
    return f"{e(spend / len(ventes))}/client" if ventes else "pas encore de client"


def roas(ca, spend):
    return "·" if not spend else ("x" + f"{ca / spend:.1f}".replace(".", ","))


def dlabel(d):
    return f"{JOURS[d.weekday()]} {d:%d/%m}"


def esc(s):
    return html.escape(str(s or ""), quote=False)


def b(s):
    return f"<b>{s}</b>"


# ---------- données ----------
def spend_day(ads, day):
    """Spend Meta du jour ; repli prorata semaine (≈) si le détail manque."""
    for r in ads.get("days", []):
        if r["date"] == day.isoformat():
            return r["spend"], True
    s = spend_range(ads, day, day)
    return s, False


def spend_between(ads, first, last):
    days = [r for r in ads.get("days", []) if first.isoformat() <= r["date"] <= last.isoformat()]
    if days:
        known = {r["date"] for r in days}
        total = sum(r["spend"] for r in days)
        # jours sans détail Meta (ex. avant le début de l'historique) : prorata semaine
        d = first
        while d <= last:
            if d.isoformat() not in known:
                total += spend_range(ads, d, d)
            d += dt.timedelta(days=1)
        return total
    return spend_range(ads, first, last)


def stats(calls, rows):
    s = {}
    s["n"] = len(rows)
    s["filled"] = [c for c in rows if c["show_up"]]
    s["pending"] = [c for c in rows if not c["show_up"]]
    s["shows"] = [c for c in rows if c["show_up"] == "OUI"]
    s["noshow"] = [c for c in rows if c["show_up"] == "NON"]
    s["reprog"] = [c for c in rows if c["show_up"] in ("REPROGRAMMER", "ANNULE")]
    s["pitched"] = [c for c in s["shows"] if c["vente"] in ("OUI", "NON", "FOLLOW_UP", "REMBOURSEMENT")]
    s["nonpitch"] = [c for c in s["shows"] if c["vente"] == "NON_PITCHE"]
    s["fu"] = [c for c in s["shows"] if c["vente"] == "FOLLOW_UP"]
    s["ventes"] = [c for c in rows if is_sale(c)]
    s["ca"] = sum(sale_amount(c) for c in s["ventes"])
    notes = [c["qualif"] for c in s["shows"] if c.get("qualif") is not None]
    s["notes"] = notes
    s["qualifies"] = sum(1 for q in notes if q >= QUALIF_MIN)
    return s


def booked_between(calls, first, last):
    return sum(1 for c in calls if c.get("booking_date")
               and first.isoformat() <= c["booking_date"] <= last.isoformat())


def ventes_detail(ventes):
    out = []
    for c in ventes:
        closer = (c.get("closer") or "").split(" ")[0]
        out.append(f"{esc(c.get('prospect') or '?')} ({esc(closer)}, {e(sale_amount(c))})")
    return ", ".join(out)


# ---------- blocs ----------
def day_block(calls, ads, day, title):
    rows = [c for c in calls if c.get("date") == day.isoformat()]
    s = stats(calls, rows)
    spend, exact = spend_day(ads, day)
    booked = booked_between(calls, day, day)
    lines = [f"🗓 {b(title + ' ' + dlabel(day))}"]
    if not rows:
        lines.append("Aucun call prévu")
    else:
        segs = [f"Calls prévus {s['n']}", f"présents {len(s['shows'])}"]
        if s["shows"] or s["noshow"]:
            segs.append(f"show-up {bpct(len(s['shows']), len(s['shows']) + len(s['noshow']))}")
        l1 = " · ".join(segs)
        extra = []
        if s["noshow"]:
            extra.append(f"no-show {len(s['noshow'])}")
        if s["reprog"]:
            extra.append(f"reprog./annulés {len(s['reprog'])}")
        if s["pending"]:
            extra.append(f"à renseigner {len(s['pending'])}")
        if extra:
            l1 += " · " + " · ".join(extra)
        lines.append(l1)
        if s["shows"]:
            q = (f"qualifiés (7+) {s['qualifies']} sur {len(s['notes'])} notés" if s["notes"]
                 else "qualif : pas de note")
            lines.append(f"Pitchés {len(s['pitched'])} · follow-ups {len(s['fu'])} · non pitchés {len(s['nonpitch'])} · {q}")
        if s["ventes"]:
            lines.append(f"✅ Ventes {len(s['ventes'])} · CA {b(e(s['ca']))} : {ventes_detail(s['ventes'])}")
        else:
            lines.append("Ventes 0 · CA 0 €")
    ads_line = f"Ads {'' if exact else '≈ '}{e(spend)} · {booked} call{'s' if booked > 1 else ''} booké{'s' if booked > 1 else ''}"
    if booked:
        ads_line += f" · {e(spend / booked)} par call booké"
    lines.append(ads_line)
    return "\n".join(lines)


def period_block(calls, ads, first, last, title):
    rows = [c for c in calls if c.get("date") and first.isoformat() <= c["date"] <= last.isoformat()]
    s = stats(calls, rows)
    spend = spend_between(ads, first, last)
    booked = booked_between(calls, first, last)
    lines = [f"📈 {b(title)} ({first:%d/%m} → {last:%d/%m})"]
    l1 = (f"Calls {len(s['filled'])} renseignés"
          + (f" (+{len(s['pending'])} à renseigner)" if s["pending"] else "")
          + f" · présents {len(s['shows'])} · show-up {bpct(len(s['shows']), len(s['shows']) + len(s['noshow']))}"
          + f" · pitchés {len(s['pitched'])} · follow-ups {len(s['fu'])}")
    lines.append(l1)
    qmoy = (" · qualif moy. " + f"{sum(s['notes']) / len(s['notes']):.1f}".replace(".", ",") + "/10"
            if s["notes"] else "")
    lines.append(f"Ventes {len(s['ventes'])} · CA {b(e(s['ca']))} · closing {pct(len(s['ventes']), len(s['shows']))} des présents"
                 f" · CA/présent {ratio(s['ca'], len(s['shows']))}{qmoy}")
    lines.append(f"Ads {e(spend)} · {booked} bookés · {ratio(spend, booked)}/booké · {ratio(spend, len(s['shows']))}/présent"
                 f" · {cost_client(spend, s['ventes'])} · ROAS {b(roas(s['ca'], spend))}")
    return "\n".join(lines)


def month_block(calls, ads, today):
    first = today.replace(day=1)
    # règle des consoles : lignes de l'onglet du mois déjà passées (ou sans date)
    rows = [c for c in calls if c["year"] == today.year and c["month"] == today.month
            and (not c.get("date") or c["date"] <= today.isoformat())]
    s = stats(calls, rows)
    total_2026 = sum(sale_amount(c) for c in calls if c["year"] == today.year and is_sale(c))
    spend = spend_between(ads, first, today)
    booked = booked_between(calls, first, today)
    lines = [f"💰 {b(MOIS[today.month - 1].upper() + ' (mois en cours)')}"]
    lines.append(f"CA signé {b(e(s['ca']))} · {len(s['ventes'])} ventes · total {today.year} : {e(total_2026)}")
    lines.append(f"Calls présents {len(s['shows'])} · show-up {pct(len(s['shows']), len(s['shows']) + len(s['noshow']))}"
                 f" · closing {pct(len(s['ventes']), len(s['shows']))} des présents · CA/présent {ratio(s['ca'], len(s['shows']))}")
    lines.append(f"Ads {e(spend)} · {booked} bookés · {ratio(spend, booked)}/booké"
                 f" · {cost_client(spend, s['ventes'])} · ROAS {b(roas(s['ca'], spend))}")
    return "\n".join(lines)


def upcoming_block(calls, today):
    def n(d1, d2):
        return sum(1 for c in calls if c.get("date") and d1.isoformat() <= c["date"] <= d2.isoformat())
    t1 = today + dt.timedelta(days=1)
    return (f"🔜 {b('À VENIR')} : demain {n(t1, t1)} call{'s' if n(t1, t1) > 1 else ''}"
            f" · 3 prochains jours {n(t1, today + dt.timedelta(days=3))}"
            f" · 7 prochains jours {n(t1, today + dt.timedelta(days=7))}")


def build_bilan(data, ads, today, now=None, data_time=None):
    """Retourne la liste des messages (1 en général, 2 si trop long)."""
    calls = data["calls"]
    now = now or dt.datetime.now(PARIS)
    head = f"📊 {b('BILAN CLOSING · ' + dlabel(today))} · {now:%H:%M}"
    if today == now.date() and now.hour < 20:
        head += " (journée en cours)"
    blocks = [head,
              day_block(calls, ads, today, "AUJOURD'HUI"),
              day_block(calls, ads, today - dt.timedelta(days=1), "HIER"),
              day_block(calls, ads, today - dt.timedelta(days=2), "AVANT-HIER"),
              period_block(calls, ads, today - dt.timedelta(days=2), today, "3 DERNIERS JOURS"),
              period_block(calls, ads, today - dt.timedelta(days=6), today, "7 DERNIERS JOURS"),
              month_block(calls, ads, today),
              upcoming_block(calls, today)]
    foot = f"Données rafraîchies le {(data_time or now):%d/%m à %H:%M} (classeur closing + Meta Ads)"
    foot += "\nRéponds 3, 7, 30... pour une période, ou « bilan » pour ce récap"
    blocks.append(foot)
    # découpe en messages < 4096 caractères, aux frontières de blocs
    msgs, cur = [], ""
    for blk in blocks:
        if cur and len(cur) + len(blk) + 2 > TG_MAX:
            msgs.append(cur)
            cur = blk
        else:
            cur = blk if not cur else cur + "\n\n" + blk
    msgs.append(cur)
    return msgs


# ---------- envoi ----------
def tg_config():
    p = os.path.join(HERE, "telegram.json")
    if os.path.exists(p):
        cfg = json.load(open(p))
        return cfg["token"], cfg["chat_id"]
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT")
    if not (tok and chat):
        sys.exit("config Telegram absente : telegram.json ou env TELEGRAM_TOKEN/TELEGRAM_CHAT")
    return tok, chat


def send_html(token, chat_id, text):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                     "disable_web_page_preview": "true"}).encode(),
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.load(resp)
    if not out.get("ok"):
        raise RuntimeError(f"échec Telegram : {out}")


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    if "--refresh" in args:
        r = subprocess.run([sys.executable, os.path.join(HERE, "refresh_data.py"), "--quiet"], cwd=HERE)
        if r.returncode != 0:
            print("⚠ refresh partiel : le bilan part avec les données disponibles", file=sys.stderr)
    data = json.load(open(os.path.join(HERE, "data.json")))
    ads = json.load(open(os.path.join(HERE, "ads.json")))
    now = dt.datetime.now(PARIS)
    today = now.date()
    if "--date" in args:
        today = dt.date.fromisoformat(args[args.index("--date") + 1])
    data_time = dt.datetime.fromtimestamp(os.path.getmtime(os.path.join(HERE, "data.json")), PARIS)
    msgs = build_bilan(data, ads, today, now, data_time)
    for m in msgs:
        print(m)
        print(f"\n[{len(m)} caractères]\n" + "=" * 60)
    if dry:
        return
    token, chat = tg_config()
    for m in msgs:
        send_html(token, chat, m)
    print(f"✓ bilan envoyé sur Telegram ({len(msgs)} message{'s' if len(msgs) > 1 else ''})")


if __name__ == "__main__":
    main()
