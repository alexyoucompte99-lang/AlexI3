#!/usr/bin/env python3
"""Envoie chaque soir 3 briefs closing sur Telegram : 3, 7 et 10 derniers jours.

Usage: python3 brief_telegram.py [--dry-run]
Config: telegram.json dans le même dossier -> {"token": "123:ABC", "chat_id": "@Alex_Maj"}
Le chat_id peut être un @canal (le bot doit y être admin) ou un id numérique
(conversation privée : envoyer /start au bot d'abord).
Données : data.json + ads.json (lancer le pipeline de refresh avant).
Le soir, les « N derniers jours » incluent la journée qui vient de se terminer.
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PERIODS = [3, 7, 10]


def fmt_e(n):
    return f"{round(n):,}".replace(",", " ") + " €"


def fmt_p(n):
    return "·" if n is None else f"{round(n)} %"


def sale_amount(c):
    return c.get("prix_confirme") or c.get("prix") or 0


def is_sale(c):
    """Vente comptée si validée par le closer (OUI) ou par Justine (virement)."""
    return c.get("vente") == "OUI" or (c.get("virement") and c.get("vente") != "REMBOURSEMENT")


def ca_mois(data, today):
    return sum(sale_amount(c) for c in data["calls"]
               if c["year"] == today.year and c["month"] == today.month and is_sale(c))


def spend_range(ads, first, last):
    """Spend ads sur [first, last], semaines proratisées au jour."""
    spend = 0.0
    for w in ads["weeks"]:
        ws = dt.date.fromisoformat(w["start"])
        we = ws + dt.timedelta(days=6)
        lo, hi = max(ws, first), min(we, last)
        if lo <= hi:
            spend += w["spend"] * ((hi - lo).days + 1) / 7
    return spend


def build_brief(data, ads, days, today):
    first = today - dt.timedelta(days=days - 1)
    f_iso, t_iso = first.isoformat(), today.isoformat()

    rows = [c for c in data["calls"] if c.get("date") and f_iso <= c["date"] <= t_iso]
    # même règle que l'onglet Suivi DATA : seuls les calls renseignés comptent
    filled = [c for c in rows if c["show_up"]]
    shows = [c for c in filled if c["show_up"] == "OUI"]
    noshow = sum(1 for c in filled if c["show_up"] == "NON")
    reprog = sum(1 for c in filled if c["show_up"] in ("REPROGRAMMER", "ANNULE"))
    # buckets disjoints : présents = pitchés + follow-ups + non pitchés (+ sans statut)
    pitched_all = [c for c in rows if c["show_up"] == "OUI"
                   and c["vente"] in ("OUI", "NON", "FOLLOW_UP", "REMBOURSEMENT")]
    fu = sum(1 for c in pitched_all if c["vente"] == "FOLLOW_UP")
    pitched = pitched_all  # dénominateur du taux de closing (follow-ups compris)
    n_pitche_seul = len(pitched_all) - fu
    non_pitche = sum(1 for c in rows if c["show_up"] == "OUI" and c["vente"] == "NON_PITCHE")
    ventes = [c for c in rows if is_sale(c)]
    ca = sum((c.get("prix_confirme") or c.get("prix") or 0) for c in ventes)
    qualifs = [c["qualif"] for c in rows if c["show_up"] == "OUI" and c.get("qualif") is not None]
    booked = sum(1 for c in data["calls"] if c.get("booking_date")
                 and f_iso <= c["booking_date"] <= t_iso)

    spend = spend_range(ads, first, today)
    spend_m = spend_range(ads, today.replace(day=1), today)

    demain = today + dt.timedelta(days=1)
    n_demain = sum(1 for c in data["calls"] if c.get("date") == demain.isoformat())
    n_3j = sum(1 for c in data["calls"] if c.get("date")
               and demain.isoformat() <= c["date"] <= (today + dt.timedelta(days=3)).isoformat())

    t_show = 100 * len(shows) / len(filled) if filled else None
    lines = [
        f"Closing · {days} derniers jours ({first.strftime('%d/%m')} → {today.strftime('%d/%m/%Y')})", "",
        f"Calls passés et renseignés : {len(filled)} · non renseignés ou à venir : {len(rows) - len(filled)}",
        f"Présents : {len(shows)} sur {len(filled)} calls renseignés, soit *{fmt_p(t_show)}* de show-up",
        f"No-show : {noshow} · reprogrammés/annulés : {reprog}",
        f"Sur les présents : {n_pitche_seul} pitché(s) + {fu} follow-up(s) + {non_pitche} non pitché(s)", "",
        f"Ventes : {len(ventes)} · CA signé sur la période : *{fmt_e(ca)}*",
        f"CA signé mois en cours : *{fmt_e(ca_mois(data, today))}*",
        f"Taux de closing : *{fmt_p(100 * len(ventes) / len(shows) if shows else None)}* des présents"
        f" · *{fmt_p(100 * len(ventes) / len(pitched) if pitched else None)}* des pitchés",
        f"CA par call présent : {fmt_e(ca / len(shows)) if shows else '·'}"
        f" · CA par call booké : {fmt_e(ca / len(filled)) if filled else '·'}",
    ]
    if spend > 0:
        lines += [
            "",
            f"Ads : {fmt_e(spend)} dépensés sur la période",
            f"Coût par call présent : {fmt_e(spend / len(shows)) if shows else '·'}"
            f" · coût par call booké : {fmt_e(spend / len(filled)) if filled else '·'}"
            f" · coût par client signé : {fmt_e(spend / len(ventes)) if ventes else 'aucune vente'}",
            f"ROAS : x{ca / spend:.2f}".replace(".", ",")
            + (f" · ROAS mois en cours : x{ca_mois(data, today) / spend_m:.2f}".replace(".", ",") if spend_m > 0 else ""),
        ]
    lines += [
        "",
        f"Qualité des leads : {sum(qualifs) / len(qualifs):.1f}/10 ({len(qualifs)} notés)".replace(".", ",")
        if qualifs else "Qualité des leads : pas de note",
        f"Résas prises sur la période : {booked}", "",
        f"À venir : {n_demain} call(s) demain · {n_3j} prévus sur les 3 prochains jours",
    ]
    return "\n".join(lines)


def send(cfg, text):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{cfg['token']}/sendMessage",
        data=urllib.parse.urlencode({"chat_id": cfg["chat_id"], "text": text, "parse_mode": "Markdown"}).encode(),
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.load(resp)
    if not out.get("ok"):
        raise RuntimeError(f"échec Telegram : {out}")


def main():
    dry = "--dry-run" in sys.argv
    data = json.load(open(os.path.join(HERE, "data.json")))
    ads = json.load(open(os.path.join(HERE, "ads.json")))
    today = dt.date.today()
    briefs = [build_brief(data, ads, d, today) for d in PERIODS]
    for b in briefs:
        print(b)
        print("\n" + "=" * 60 + "\n")
    if dry:
        return
    cfg_path = os.path.join(HERE, "telegram.json")
    if not os.path.exists(cfg_path):
        sys.exit("telegram.json manquant : {'token': '...', 'chat_id': '@Alex_Maj'} "
                 "(créer le bot via @BotFather, puis l'ajouter au canal ou lui envoyer /start)")
    cfg = json.load(open(cfg_path))
    for b in briefs:
        send(cfg, b)
        time.sleep(1)
    print("✓ 3 messages envoyés sur Telegram")


if __name__ == "__main__":
    main()
