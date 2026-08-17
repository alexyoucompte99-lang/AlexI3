#!/usr/bin/env python3
"""Prépare closing-data.json pour la console closing (calls 2026 enrichis).

Usage: python3 aggregate_closing.py data.json closing-data.json "10/08/2026 22:00"
"""
import datetime as dt
import json
import re
import sys

RELANCE_KWS = r"(relance|relanc|rappel|rappeler|recontact|revenir|reviens|retour|follow[- ]?up|redonner|redonnera|news|nouvelles|sms|r2|rdv|prevu|prévu|planifi|inscription|point)"
PASSE_KWS = r"(depuis|il y a|ya|y a|ca fait|ça fait)\s*$"
MOIS_FR = {"janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5,
           "juin": 6, "juillet": 7, "aout": 8, "août": 8, "septembre": 9,
           "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12}
JOURS_FR = {"lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4,
            "samedi": 5, "dimanche": 6}


def relance_estimee(com, call_date):
    """Estime la date de relance depuis le commentaire closing (texte libre).

    Formats couverts : dates jj/mm près d'un mot-clé de relance, « 4 mai »,
    « début juin », jours de la semaine, « demain », « dans X jours »,
    « semaine pro », « quinzaine ». Les mentions tournées vers le passé
    (« depuis 2 mois », « il y a 3 jours ») sont écartées.
    """
    if not com or not call_date:
        return None
    try:
        base = dt.date.fromisoformat(call_date)
    except ValueError:
        return None
    low = com.lower()
    cands = []

    def past_ref(start):
        return re.search(PASSE_KWS, low[max(0, start - 14):start])

    def keep(cand):
        if base <= cand <= base + dt.timedelta(days=120):
            cands.append(cand)

    # jj/mm(/aa) près d'un mot-clé de relance
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", low):
        d, mo = int(m.group(1)), int(m.group(2))
        if not (1 <= d <= 31 and 1 <= mo <= 12) or past_ref(m.start()):
            continue
        y = int(m.group(3)) if m.group(3) else base.year
        if y < 100:
            y += 2000
        try:
            cand = dt.date(y, mo, d)
        except ValueError:
            continue
        if not m.group(3) and cand < base:
            cand = dt.date(y + 1, mo, d)
        if re.search(RELANCE_KWS, low[max(0, m.start() - 80):m.end() + 80]):
            keep(cand)

    # « 4 mai », « 1er juin »
    for m in re.finditer(r"\b(\d{1,2})(?:er)?\s+(" + "|".join(MOIS_FR) + r")\b", low):
        if past_ref(m.start()):
            continue
        d, mo = int(m.group(1)), MOIS_FR[m.group(2)]
        if not 1 <= d <= 31:
            continue
        y = base.year
        try:
            cand = dt.date(y, mo, d)
        except ValueError:
            continue
        if cand < base:
            cand = dt.date(y + 1, mo, d)
        keep(cand)

    # « début juin », « mi-juin », « fin juin »
    for m in re.finditer(r"\b(debut|début|mi|fin)[\s-]+(" + "|".join(MOIS_FR) + r")\b", low):
        if past_ref(m.start()):
            continue
        day = {"debut": 3, "début": 3, "mi": 15, "fin": 25}[m.group(1)]
        mo = MOIS_FR[m.group(2)]
        cand = dt.date(base.year, mo, day)
        if cand < base:
            cand = dt.date(base.year + 1, mo, day)
        keep(cand)

    # jours de la semaine (prochaine occurrence après le call)
    for m in re.finditer(r"\b(" + "|".join(JOURS_FR) + r")\b", low):
        if past_ref(m.start()):
            continue
        # évite le doublon avec « lundi 4 mai » (déjà couvert au-dessus)
        after = low[m.end():m.end() + 14]
        if re.match(r"\s+\d", after):
            continue
        delta = (JOURS_FR[m.group(1)] - base.weekday() - 1) % 7 + 1
        keep(base + dt.timedelta(days=delta))

    # expressions relatives
    m = re.search(r"\bdans\s+(\d{1,2})\s+jours?\b", low)
    if m and not past_ref(m.start()):
        keep(base + dt.timedelta(days=int(m.group(1))))
    for pat, days in [(r"apres[- ]demain|après[- ]demain", 2), (r"\bdemain\b", 1),
                      (r"semaine\s+pro(chaine)?\b", 7), (r"dans la semaine", 5),
                      (r"quinzaine", 15), (r"dans quelques jours", 4),
                      (r"dans un mois|mois prochain", 30), (r"la rentree|la rentrée", None)]:
        m = re.search(pat, low)
        if m and not past_ref(m.start()):
            if days is None:  # la rentrée = 1er septembre
                cand = dt.date(base.year, 9, 1)
                if cand < base:
                    cand = dt.date(base.year + 1, 9, 1)
                keep(cand)
            else:
                keep(base + dt.timedelta(days=days))

    return min(cands).isoformat() if cands else None


def main(data_path, out_path, updated_at):
    d = json.load(open(data_path))
    calls = []
    for c in d["calls"]:
        if c["year"] != 2026:
            continue
        prix_eff = c.get("prix_confirme") or c.get("prix") or 0
        calls.append({
            "d": c.get("date"),
            "b": c.get("booking_date"),
            "tm": f"{c['year']:04d}-{c['month']:02d}",
            "c": re.sub(r"\s+", " ", c.get("closer") or "").strip(),
            "n": (c.get("prospect") or "").strip(),
            "tel": c.get("phone") or "",
            "mail": c.get("mail") or "",
            "s": c.get("show_up") or "",
            "v": c.get("vente") or "",
            "q": c.get("qualif"),
            "pp": round(c.get("prix") or 0),          # prix proposé
            # vente comptée si validée par le closer (OUI) OU par Justine (virement)
            "p": round(prix_eff) if (c.get("vente") in ("OUI", "REMBOURSEMENT") or c.get("virement")) else 0,
            "vir": bool(c.get("virement")),
            "com": (c.get("commentaire") or "").strip(),
            "obj": (c.get("objection") or "").strip(),
            "rel": c.get("relance"),
            "r2": c.get("r2"),
            "relEst": relance_estimee(c.get("commentaire"), c.get("date")),
            "hasS": bool(c.get("has_show_up_raw")),
            "hasV": bool(c.get("has_vente_raw")),
        })

    eod_appel = [r for r in d.get("setter_reports", []) if r.get("year") == 2026]
    eod_ecrit = [r for r in d.get("dm_reports", []) if r.get("year") == 2026]
    # semaines ads (spend + résas) pour le brief : chargées depuis ads.json si présent
    weeks = []
    try:
        import os
        ads_path = os.path.join(os.path.dirname(os.path.abspath(out_path)) or ".", "ads.json")
        ads = json.load(open(ads_path))
        weeks = [{"start": w["start"], "spend": w["spend"], "booked": w["calls_booked"]}
                 for w in ads.get("weeks", [])]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    out = {"updated_at": updated_at, "calls": calls,
           "eod_appel": eod_appel, "eod_ecrit": eod_ecrit, "weeks": weeks}
    with open(out_path, "w") as f:
        json.dump(out, f, ensure_ascii=False)

    fu = [c for c in calls if c["v"] == "FOLLOW_UP"]
    nv = [c for c in calls if c["v"] == "OUI" and not c["vir"]]
    print(f"calls={len(calls)} follow-ups={len(fu)} ventes sans virement={len(nv)}",
          file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
