#!/usr/bin/env python3
"""Prise de recul quotidienne « cap 100 k » : UN message Telegram le matin
(objectif du mois, alertes, la chaîne du funnel, le goulot) + un second message
avec le récap prêt à envoyer à Thomas (bloc à copier + lien WhatsApp).

Règles identiques aux consoles et aux briefs : vente = OUI closer OU virement
Justine, CA = prix confirmé sinon proposé, vente comptée le jour du cochage
(registre sales_ledger), show-up = OUI / (OUI + NON). Les fenêtres 7 j et 28 j
sont des jours RÉVOLUS (hier compris, aujourd'hui exclu) : le matin, la veille
est complète. « Prévus » = toutes les lignes de calls datées dans la fenêtre
(reprogrammés, annulés et non renseignés compris) ; « rendement » = présents /
prévus, c'est le vrai rendement d'un call booké.

Usage : python3 pilotage.py [--dry-run] [--refresh] [--date AAAA-MM-JJ]
                            [--thomas] [--json]
  --refresh : lance refresh_data.py avant (pont Apps Script + Meta)
  --thomas  : n'affiche que le récap Thomas (texte brut WhatsApp)
  --json    : dump des chiffres (pour le brainstorm /recul)
Config : telegram.json (ou env TELEGRAM_TOKEN / TELEGRAM_CHAT) ;
numéro WhatsApp de Thomas : env WA_THOMAS ou private.json ; objectif : env
OBJECTIF_CA_MOIS (défaut 100 000).
"""
import datetime as dt
import json
import math
import os
import subprocess
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from brief_telegram import is_sale, last_sale, sale_amount, sale_day  # noqa: E402
from brief_bilan import (PARIS, MOIS, b, booked_between, dlabel, e, esc,  # noqa: E402
                         pct, roas, send_html, spend_between, tg_config)

OBJECTIF = int(os.environ.get("OBJECTIF_CA_MOIS") or 100_000)
# Références du modèle 100 k (éditables). Juillet 2026 = 24 % de closing des
# présents, août = 50 % de rendement (présents / calls prévus), 44 €/booké.
CIBLE_CLOSING = 0.25       # ventes / présents
CIBLE_NON_PITCHE = 0.20    # au-delà de cette part de présents non pitchés : alerte
PANIER_DEFAUT = 3900       # si moins de 3 ventes sur 90 j
SANS_VENTE_ORANGE, SANS_VENTE_ROUGE = 4, 7
FU_MIN_AGE, FU_MAX_AGE = 3, 45   # follow-ups « à relancer » : entre 3 et 45 j
JOURS_MOIS = 30.4


# ---------- outils ----------
def rate(num, den):
    return None if not den else num / den


def fp(x, digits=0):
    """Pourcentage depuis un ratio (0,13 -> « 13 % »)."""
    if x is None:
        return "·"
    v = round(100 * x, digits)
    return f"{int(v) if digits == 0 else v} %".replace(".", ",")


def fk(n):
    """Milliers courts : 18 350 -> « 18 k€ »."""
    return f"{n / 1000:.0f} k€" if abs(n) >= 1000 else e(n)


def roas_txt(ca, spend):
    return "·" if not spend else roas(ca, spend)


def nl(x, s="s"):
    return s if x > 1 else ""


def rows_between(calls, first, last):
    f, t = first.isoformat(), last.isoformat()
    return [c for c in calls if c.get("date") and f <= c["date"] <= t]


def window(calls, ads, first, last):
    rows = rows_between(calls, first, last)
    shows = [c for c in rows if c["show_up"] == "OUI"]
    noshow = [c for c in rows if c["show_up"] == "NON"]
    pending = [c for c in rows if not c["show_up"]]
    reprog = [c for c in rows if c["show_up"] in ("REPROGRAMMER", "ANNULE")]
    pitched = [c for c in shows if c["vente"] in ("OUI", "NON", "REMBOURSEMENT")]
    fu = [c for c in shows if c["vente"] == "FOLLOW_UP"]
    nonp = [c for c in shows if c["vente"] == "NON_PITCHE"]
    f, t = first.isoformat(), last.isoformat()
    ventes = [c for c in calls if is_sale(c) and f <= sale_day(c) <= t]
    return {
        "first": first, "last": last, "days": (last - first).days + 1,
        "n": len(rows), "shows": len(shows), "noshow": len(noshow), "pending": len(pending),
        "reprog": len(reprog), "pitched": len(pitched), "fu": len(fu), "nonp": len(nonp),
        "ventes": len(ventes), "ca": sum(sale_amount(c) for c in ventes),
        "spend": spend_between(ads, first, last), "booked": booked_between(calls, first, last),
        "showup": rate(len(shows), len(shows) + len(noshow) + len(pending)),
        "rendement": rate(len(shows), len(rows)),
        "closing": rate(len(ventes), len(shows)),
        "part_nonp": rate(len(nonp), len(shows)),
    }


def panier_moyen(calls, today):
    f = (today - dt.timedelta(days=90)).isoformat()
    v = [sale_amount(c) for c in calls if is_sale(c) and f <= sale_day(c) <= today.isoformat()]
    return (sum(v) / len(v)) if len(v) >= 3 else PANIER_DEFAUT


def followups_a_relancer(calls, today):
    lo = (today - dt.timedelta(days=FU_MAX_AGE)).isoformat()
    hi = (today - dt.timedelta(days=FU_MIN_AGE)).isoformat()
    return [c for c in calls if c.get("date") and lo <= c["date"] <= hi
            and c["show_up"] == "OUI" and c["vente"] == "FOLLOW_UP"
            and not c.get("relance_faite") and not c.get("r2")]


def plus_long_trou(calls, since):
    days = sorted({sale_day(c) for c in calls if is_sale(c) and sale_day(c) >= since.isoformat()})
    best, prev = 0, None
    for d in days:
        if prev:
            best = max(best, (dt.date.fromisoformat(d) - dt.date.fromisoformat(prev)).days)
        prev = d
    return best


# ---------- calcul ----------
def compute(data, ads, today, now=None):
    calls = data["calls"]
    now = now or dt.datetime.now(PARIS)
    hier = today - dt.timedelta(days=1)
    w7 = window(calls, ads, today - dt.timedelta(days=7), hier)
    w28 = window(calls, ads, today - dt.timedelta(days=28), hier)
    w7p = window(calls, ads, today - dt.timedelta(days=14), today - dt.timedelta(days=8))

    # mois en cours
    first = today.replace(day=1)
    dim = (first.replace(month=first.month % 12 + 1, year=first.year + (first.month == 12))
           - dt.timedelta(days=1)).day
    fin_mois = first.replace(day=dim)
    elapsed = today.day if now.hour >= 20 else max(1, today.day - 1)
    m = window(calls, ads, first, today)
    panier = panier_moyen(calls, today)
    proj = m["ca"] / elapsed * dim
    reste = max(0.0, OBJECTIF - m["ca"])
    ventes_restantes = math.ceil(reste / panier) if reste else 0
    jours_restants = dim - elapsed

    # dernière vente
    ls = last_sale(calls, today)
    sans_vente = (today - dt.date.fromisoformat(ls[0])).days if ls else None
    trou_max = plus_long_trou(calls, today - dt.timedelta(days=90))

    # modèle 100 k (rythmes des 28 derniers jours mensualisés)
    k = JOURS_MOIS / 28
    ventes_obj = OBJECTIF / panier
    presents_mois = w28["shows"] * k
    prevus_mois = w28["n"] * k
    spend_mois = w28["spend"] * k
    cpb = rate(w28["spend"], w28["booked"])
    rend = w28["rendement"]
    closing_need_now = rate(ventes_obj, presents_mois)
    besoin_now = besoin_cible = None
    if w28["closing"] and rend:
        p = ventes_obj / w28["closing"]
        besoin_now = {"presents": p, "prevus": p / rend, "spend": (p / rend) * (cpb or 0)}
    if rend:
        p = ventes_obj / CIBLE_CLOSING
        besoin_cible = {"presents": p, "prevus": p / rend, "spend": (p / rend) * (cpb or 0)}

    fus = followups_a_relancer(calls, today)
    non_rens = [c for c in rows_between(calls, today - dt.timedelta(days=7), hier) if not c["show_up"]]

    # fraîcheur Meta : dernier jour de spend remonté
    days_ads = ads.get("days", [])
    last_ads = days_ads[-1]["date"] if days_ads else None
    spend_2j = sum(r["spend"] for r in days_ads[-2:]) if days_ads else 0

    return {
        "today": today, "now": now, "w7": w7, "w28": w28, "w7p": w7p, "m": m,
        "dim": dim, "elapsed": elapsed, "fin_mois": fin_mois, "panier": panier, "proj": proj,
        "reste": reste, "ventes_restantes": ventes_restantes, "jours_restants": jours_restants,
        "last_sale": ls, "sans_vente": sans_vente, "trou_max": trou_max,
        "ventes_obj": ventes_obj, "presents_mois": presents_mois, "prevus_mois": prevus_mois,
        "spend_mois": spend_mois, "cpb": cpb, "closing_need_now": closing_need_now,
        "besoin_now": besoin_now, "besoin_cible": besoin_cible,
        "fus": fus, "non_rens": non_rens, "last_ads": last_ads, "spend_2j": spend_2j,
    }


# ---------- alertes ----------
def alertes(x):
    out = []
    w7, w28 = x["w7"], x["w28"]
    sv, ls = x["sans_vente"], x["last_sale"]
    if sv is None:
        out.append(("🔴", "aucune vente enregistrée"))
    else:
        lvl = "🔴" if sv >= SANS_VENTE_ROUGE else "🟠" if sv >= SANS_VENTE_ORANGE else "🟢"
        d = dt.date.fromisoformat(ls[0])
        txt = (f"{b(str(sv) + ' jour' + nl(sv) + ' sans vente')} (dernière : {dlabel(d)}, "
               f"{esc(ls[1])}, {esc(ls[2])}, {e(ls[3])})")
        if sv >= SANS_VENTE_ORANGE:
            txt += f" · plus long trou sur 90 j : {x['trou_max']} j"
        out.append((lvl, txt))
    n = len(x["fus"])
    if n:
        out.append(("🔴" if n >= 10 else "🟠", f"{n} follow-up{nl(n)} de 3 à 45 j sans relance cochée ni R2"))
    else:
        out.append(("🟢", "follow-ups : tout est relancé"))
    if w7["shows"] >= 5 and w7["part_nonp"] is not None and w7["part_nonp"] > CIBLE_NON_PITCHE:
        out.append(("🔴" if w7["part_nonp"] > 0.45 else "🟠",
                    f"{w7['nonp']} présent{nl(w7['nonp'])} sur {w7['shows']} non pitché{nl(w7['nonp'])} sur 7 j ({fp(w7['part_nonp'])})"))
    if w7["showup"] is not None and w28["showup"] is not None:
        d = w7["showup"] - w28["showup"]
        out.append(("🟠" if d < -0.10 else "🟢", f"show-up 7 j {fp(w7['showup'])} (28 j : {fp(w28['showup'])})"))
    moy = w28["booked"] / 4
    if moy:
        r = w7["booked"] / moy
        out.append(("🔴" if r < 0.5 else "🟠" if r < 0.75 else "🟢",
                    f"{w7['booked']} call{nl(w7['booked'])} booké{nl(w7['booked'])} sur 7 j (moy. 4 sem. : {moy:.0f})"))
    if x["last_ads"]:
        la = dt.date.fromisoformat(x["last_ads"])
        age = (x["today"] - la).days
        if age > 2:
            out.append(("🟠", f"Meta : pas de dépense remontée depuis le {la:%d/%m} (token ?)"))
        elif x["spend_2j"] <= 0:
            out.append(("🔴", "Meta : 0 € dépensé sur les 2 derniers jours (pubs coupées ?)"))
        else:
            moy_s = w28["spend"] / 4
            r = w7["spend"] / moy_s if moy_s else 1
            out.append(("🟠" if r < 0.6 else "🟢", f"ads 7 j {e(w7['spend'])} (moy. 4 sem. : {e(moy_s)})"))
    nr = len(x["non_rens"])
    if nr:
        out.append(("🟠" if nr >= 3 else "🟢", f"{nr} call{nl(nr)} passé{nl(nr)} non renseigné{nl(nr)} sur 7 j"))
    return out


# ---------- goulot ----------
def goulot(x):
    w28 = x["w28"]
    if not w28["shows"]:
        return "Pas assez de calls présents sur 28 j pour juger : le sujet n°1 est le volume."
    vo = x["ventes_obj"]
    parts = []
    gc = (CIBLE_CLOSING / w28["closing"]) if w28["closing"] else float("inf")
    gv = (x["besoin_cible"]["presents"] / x["presents_mois"]) if x["besoin_cible"] and x["presents_mois"] else 1
    closing_first = gc >= gv
    lev_closing = (f"{b('Closing')} : {fp(w28['closing'])} des présents sur 28 j (cible {fp(CIBLE_CLOSING)}, "
                   f"juillet 24 %). Au volume actuel ({x['presents_mois']:.0f} présents/mois) il faudrait "
                   f"{fp(x['closing_need_now'])} pour {fk(OBJECTIF)}.")
    if w28["part_nonp"] is not None and w28["part_nonp"] > CIBLE_NON_PITCHE:
        lev_closing += (f" {w28['nonp']} présents sur {w28['shows']} non pitchés ({fp(w28['part_nonp'])}) : "
                        f"c'est là que ça fuit (qualification avant le call, conjoint présent).")
    if x["besoin_cible"]:
        bc = x["besoin_cible"]
        lev_volume = (f"{b('Volume')} : {x['presents_mois']:.0f} présents/mois "
                      f"({x['prevus_mois']:.0f} calls prévus, {fk(x['spend_mois'])} d'ads). "
                      f"À {fp(CIBLE_CLOSING)} de closing il en faut {bc['presents']:.0f} "
                      f"(≈ {bc['prevus']:.0f} calls, ≈ {fk(bc['spend'])} d'ads à {e(x['cpb'] or 0)}/booké).")
    else:
        lev_volume = f"{b('Volume')} : {x['presents_mois']:.0f} présents/mois."
    order = [lev_closing, lev_volume] if closing_first else [lev_volume, lev_closing]
    parts.append("Levier n°1 · " + order[0])
    parts.append("Levier n°2 · " + order[1])
    if x["besoin_now"]:
        bn = x["besoin_now"]
        parts.append(f"Sans toucher au closing : {bn['presents']:.0f} présents/mois "
                     f"(≈ {bn['prevus']:.0f} calls, ≈ {fk(bn['spend'])} d'ads).")
    parts.append(f"{fk(OBJECTIF)} = {vo:.0f} ventes/mois au panier de {e(x['panier'])} "
                 f"= {vo / JOURS_MOIS:.1f}".replace(".", ",") + " vente/jour.")
    return "\n".join(parts)


# ---------- messages ----------
def build_pilotage(x, data_time=None):
    today, now, m, w7, w28 = x["today"], x["now"], x["m"], x["w7"], x["w28"]
    mois = MOIS[today.month - 1].upper()
    head = f"🎯 {b('PRISE DE RECUL · ' + dlabel(today))} · {now:%H:%M}"
    if data_time:
        head += f"\n🔄 Données du {data_time:%d/%m à %H:%M} (classeur closing + Meta Ads)"
    cap = [f"💰 {b('CAP ' + fk(OBJECTIF) + ' · ' + mois)} · jour {x['elapsed']}/{x['dim']}",
           f"CA signé {b(e(m['ca']))} · {m['ventes']} vente{nl(m['ventes'])}",
           f"Rythme actuel → {b(e(x['proj']))} fin de mois ({fp(x['proj'] / OBJECTIF)} de l'objectif)"]
    if x["reste"]:
        cap.append(f"Reste {e(x['reste'])} = {x['ventes_restantes']} vente{nl(x['ventes_restantes'])} "
                   f"en {x['jours_restants']} j"
                   + (f" ({x['ventes_restantes'] / x['jours_restants']:.1f}/jour)".replace(".", ",")
                      if x["jours_restants"] > 0 else ""))
    else:
        cap.append("Objectif atteint ✅")
    al = [f"🚨 {b('ALERTES')}"] + [f"{lvl} {txt}" for lvl, txt in alertes(x)]
    ch = [f"📉 {b('LA CHAÎNE · 7 derniers jours')} ({w7['first']:%d/%m} → {w7['last']:%d/%m}, entre parenthèses : 28 j)",
          f"Ads {e(w7['spend'])} → {w7['booked']} booké{nl(w7['booked'])} · "
          f"{e(rate(w7['spend'], w7['booked']) or 0)}/booké ({e(x['cpb'] or 0)})",
          f"{w7['n']} call{nl(w7['n'])} prévu{nl(w7['n'])} → {w7['shows']} présent{nl(w7['shows'])} · "
          f"rendement {fp(w7['rendement'])} ({fp(w28['rendement'])}) · show-up {fp(w7['showup'])} ({fp(w28['showup'])})",
          f"Présents = {w7['pitched']} pitché{nl(w7['pitched'])} + {w7['fu']} follow-up{nl(w7['fu'])} + "
          f"{w7['nonp']} non pitché{nl(w7['nonp'])}",
          f"→ {w7['ventes']} vente{nl(w7['ventes'])} · {b(e(w7['ca']))} · closing {fp(w7['closing'])} "
          f"des présents ({fp(w28['closing'])})",
          f"ROAS {b(roas_txt(w7['ca'], w7['spend']))} (28 j : {roas_txt(w28['ca'], w28['spend'])}) · "
          f"28 j : {w28['ventes']} vente{nl(w28['ventes'])}, {e(w28['ca'])}"]
    go = [f"🧭 {b('LE GOULOT')}", goulot(x)]
    foot = "Réponds « thomas » pour le récap à lui envoyer, « bilan » pour le détail jour par jour"
    return "\n\n".join([head, "\n".join(cap), "\n".join(al), "\n".join(ch),
                        "\n".join(go), foot])


def build_recap_thomas(x):
    """Texte brut (WhatsApp) : court, factuel, une action à compléter par Alex."""
    today, m, w7, w28 = x["today"], x["m"], x["w7"], x["w28"]
    mois = MOIS[today.month - 1].capitalize()
    lines = [f"Point I3 · {dlabel(today)}", ""]
    lines.append(f"{mois} : {e(m['ca'])} signés ({m['ventes']} vente{nl(m['ventes'])}). "
                 f"Rythme actuel : {e(x['proj'])} fin de mois, objectif {e(OBJECTIF)}.")
    lines.append(f"7 derniers jours : {w7['booked']} call{nl(w7['booked'])} booké{nl(w7['booked'])}, "
                 f"{w7['shows']} présent{nl(w7['shows'])}, {w7['ventes']} vente{nl(w7['ventes'])}, "
                 f"{e(w7['spend'])} d'ads, ROAS {roas_txt(w7['ca'], w7['spend'])}.")
    pts = []
    if x["sans_vente"] is not None and x["sans_vente"] >= SANS_VENTE_ORANGE:
        pts.append(f"{x['sans_vente']} jours sans vente")
    if w7["shows"] >= 5:
        pts.append(f"closing {fp(w7['closing'])} des présents sur 7 j ({fp(w28['closing'])} sur 28 j, 24 % en juillet)")
        if w7["part_nonp"] and w7["part_nonp"] > CIBLE_NON_PITCHE:
            pts.append(f"{w7['nonp']} présents sur {w7['shows']} non pitchés")
    if len(x["fus"]) >= 5:
        pts.append(f"{len(x['fus'])} follow-ups à relancer")
    if pts:
        lines.append("Points d'attention : " + " · ".join(pts) + ".")
    lines.append("Action de la semaine : (à compléter)")
    return "\n".join(lines)


def wa_number():
    n = os.environ.get("WA_THOMAS")
    if not n:
        p = os.path.join(HERE, "private.json")
        if os.path.exists(p):
            n = json.load(open(p)).get("WA_THOMAS")
    return "".join(ch for ch in (n or "") if ch.isdigit())


def build_thomas_message(recap):
    txt = f"✍️ {b('RÉCAP THOMAS')} (touche le bloc pour le copier, complète l'action)\n\n<pre>{esc(recap)}</pre>"
    num = wa_number()
    if num:
        url = f"https://wa.me/{num}?text={urllib.parse.quote(recap)}"
        txt += f'\n\n<a href="{url}">Ouvrir WhatsApp avec le récap pré-rempli</a>'
    return txt


def to_json(x):
    def w(v):
        return {k: (val.isoformat() if isinstance(val, dt.date) else val) for k, val in v.items()}
    return {
        "date": x["today"].isoformat(), "objectif": OBJECTIF, "panier": round(x["panier"]),
        "mois": w(x["m"]), "projection": round(x["proj"]), "reste": round(x["reste"]),
        "ventes_restantes": x["ventes_restantes"], "jours_restants": x["jours_restants"],
        "sans_vente_jours": x["sans_vente"], "derniere_vente": x["last_sale"], "trou_max_90j": x["trou_max"],
        "j7": w(x["w7"]), "j28": w(x["w28"]), "j7_precedent": w(x["w7p"]),
        "modele_100k": {"ventes_par_mois": round(x["ventes_obj"], 1),
                        "presents_mois_actuels": round(x["presents_mois"]),
                        "prevus_mois_actuels": round(x["prevus_mois"]),
                        "spend_mois_actuel": round(x["spend_mois"]),
                        "closing_necessaire_au_volume_actuel": x["closing_need_now"],
                        "besoin_au_closing_actuel": x["besoin_now"],
                        "besoin_a_25pct": x["besoin_cible"]},
        "followups_a_relancer": [{"date": c["date"], "prospect": c.get("prospect"), "closer": c.get("closer"),
                                  "prix": c.get("prix"), "qualif": c.get("qualif")} for c in x["fus"]],
        "non_renseignes_7j": len(x["non_rens"]),
        "alertes": [f"{l} {t}" for l, t in alertes(x)],
    }


def main():
    args = sys.argv[1:]
    if "--refresh" in args:
        r = subprocess.run([sys.executable, os.path.join(HERE, "refresh_data.py"), "--quiet"], cwd=HERE)
        if r.returncode != 0:
            print("⚠ refresh partiel : on part avec les données disponibles", file=sys.stderr)
    data = json.load(open(os.path.join(HERE, "data.json")))
    ads = json.load(open(os.path.join(HERE, "ads.json")))
    now = dt.datetime.now(PARIS)
    today = now.date()
    if "--date" in args:
        today = dt.date.fromisoformat(args[args.index("--date") + 1])
    x = compute(data, ads, today, now)
    recap = build_recap_thomas(x)
    if "--json" in args:
        print(json.dumps(to_json(x), ensure_ascii=False, indent=1, default=str))
        return
    if "--thomas" in args:
        print(recap)
        return
    data_time = dt.datetime.fromtimestamp(os.path.getmtime(os.path.join(HERE, "data.json")), PARIS)
    msg1 = build_pilotage(x, data_time)
    msg2 = build_thomas_message(recap)
    for m in (msg1, msg2):
        print(m)
        print(f"\n[{len(m)} caractères]\n" + "=" * 60)
    if "--dry-run" in args:
        return
    token, chat = tg_config()
    for m in (msg1, msg2):
        send_html(token, chat, m)
    print("✓ prise de recul envoyée sur Telegram (2 messages)")


if __name__ == "__main__":
    main()
