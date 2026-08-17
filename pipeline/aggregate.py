#!/usr/bin/env python3
"""Prépare dashboard-data.json : calls bruts compacts + semaines ads + méta.

Tout le calcul (KPI, funnel, closers, sources, hygiène) se fait côté page,
ce qui permet les filtres de dates et de closers.

Usage: python3 aggregate.py data.json ads.json dashboard-data.json "08/08/2026 09:00"
"""
import json
import re
import sys
from collections import defaultdict


def source_category(c):
    # le canal vit dans l'UTM / source2 / provenance ; "Source du call" est un
    # type d'appel, utile seulement pour détecter le webinaire (Live)
    if c.get("webi"):
        return "Webinaire"
    call_type = (c.get("source") or "").lower()
    txt = " ".join(filter(None, [c.get("utm") or "", c.get("source2") or "",
                                 c.get("lead_source") or ""])).lower().strip()
    if "live" in call_type or "webi" in call_type or "live" in txt or "webi" in txt:
        return "Webinaire"
    if not txt or txt == "no data":
        return "Non renseigné"
    if "relance" in txt:
        return "Relance"
    if "setting" in txt:
        return "Setting"
    if "site web" in txt:
        return "Site web"
    if "youtube" in txt:
        return "YouTube"
    if ("broad" in txt or "vsl" in txt or "creative" in txt or "funnel" in txt
            or re.search(r"\bads?\+?\s*n?°?\d", txt) or "utm" in txt
            or re.search(r"\bad\d", txt)):
        return "Facebook Ads"
    return "Autre"


def main(data_path, ads_path, out_path, updated_at):
    d = json.load(open(data_path))
    ads = json.load(open(ads_path))

    calls = []
    for c in d["calls"]:
        prix = c.get("prix_confirme") or c.get("prix") or 0
        sale = c.get("vente") in ("OUI", "REMBOURSEMENT") or c.get("virement")
        flags = (1 if c.get("has_show_up_raw") else 0) \
              | (2 if c.get("has_vente_raw") else 0) \
              | (4 if c.get("has_qualif_raw") else 0)
        calls.append({
            "d": c.get("date"),                       # date réelle du call (ou null)
            "tm": f"{c['year']:04d}-{c['month']:02d}",  # mois de l'onglet
            "c": re.sub(r"\s+", " ", c.get("closer") or "").strip(),
            "n": (c.get("prospect") or "").strip(),
            "s": c.get("show_up") or "",
            "v": c.get("vente") or "",
            "q": c.get("qualif"),
            "p": round(prix) if sale else 0,
            "vir": bool(c.get("virement")),
            "g": source_category(c),
            "f": flags,
        })

    weeks = []
    for w in ads["weeks"]:
        w = dict(w)
        w["month"] = int(w["start"][5:7])
        weeks.append(w)

    stripe_by_month = defaultdict(float)
    for s in d["stripe"]:
        stripe_by_month[f"{s['year']}-{s['month']:02d}"] += s["montant_ttc"]
    stripe_months = [{"month": k, "total": round(v)} for k, v in sorted(stripe_by_month.items())]

    out = {
        "updated_at": updated_at,
        "calls": calls,
        "weeks": weeks,
        "stripe_months": stripe_months,
    }
    with open(out_path, "w") as f:
        json.dump(out, f, ensure_ascii=False)

    n26 = sum(1 for c in calls if c["tm"].startswith("2026"))
    v26 = sum(1 for c in calls if c["tm"].startswith("2026") and c["v"] == "OUI")
    ca26 = sum(c["p"] for c in calls if c["tm"].startswith("2026"))
    print(f"calls={len(calls)} (2026: {n26}) ventes 2026={v26} ca 2026={ca26}", file=sys.stderr)
    print(f"weeks={len(weeks)} spend={sum(w['spend'] for w in weeks):.0f}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
