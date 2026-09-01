#!/usr/bin/env python3
"""Registre des dates de vente (règle Alex 01/09/2026 : la vente est comptée le
jour où elle est cochée, pas le jour du premier call).

Le Sheet n'enregistre pas quand VENTE passe à OUI : ce script note, pour chaque
vente (VENTE=OUI/REMBOURSEMENT ou virement Justine), la date du premier run qui
la voit, et annote data.json en place (champ sale_date sur les calls vendus).
Consoles et briefs utilisent ensuite sale_date (repli : date du call).

Usage: python3 sales_ledger.py data.json <chemin du registre .sales-ledger.json>

Le registre est commité dans le repo public AlexI3 : clés anonymisées
(sha1 onglet|prospect|date du call, 16 hex). Les ventes présentes au seed du
registre (01/09/2026) sont stockées avec "" = repli sur la date du call.
"""
import datetime as dt
import hashlib
import json
import os
import sys
import zoneinfo


def is_sold(c):
    return c.get("vente") in ("OUI", "REMBOURSEMENT") or c.get("virement")


def key(c):
    raw = f"{c.get('tab', '')}|{(c.get('prospect') or '').strip().lower()}|{c.get('date') or ''}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def main(data_path, ledger_path):
    d = json.load(open(data_path))
    seeding = not os.path.exists(ledger_path)
    ledger = {} if seeding else json.load(open(ledger_path))
    today = dt.datetime.now(zoneinfo.ZoneInfo("Europe/Paris")).date().isoformat()
    new = 0
    for c in d["calls"]:
        if not is_sold(c):
            continue
        k = key(c)
        if k not in ledger:
            # seed : vente déjà là avant le registre -> "" (repli date du call)
            ledger[k] = "" if seeding else today
            new += 1
        c["sale_date"] = ledger[k] or None
    json.dump(ledger, open(ledger_path, "w"), indent=0, sort_keys=True)
    json.dump(d, open(data_path, "w"))
    print(f"sales_ledger: {len(ledger)} ventes au registre, {new} nouvelle(s)"
          + (" (seed : date du call)" if seeding else ""), file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: sales_ledger.py data.json .sales-ledger.json")
    main(sys.argv[1], sys.argv[2])
