#!/usr/bin/env python3
"""Contrôle : les deux consoles donnent-elles les mêmes ventes et le même CA par mois ?

Règle commune (Alex 01/09/2026) : date de vente = jour du cochage dans la console
closing (champ sd posé par sales_ledger.py, repli sur la date du call pour les
ventes antérieures au registre), vente = VENTE OUI ou virement Justine (hors
remboursement), CA = prix confirmé sinon proposé.

Usage: python3 check_ventes.py [closing-data.json] [dashboard-data.json]
Affiche mois par mois ventes/CA côté closing et côté business, l'écart, et pour
mémoire les anciennes règles de la console business (mois de l'onglet pour le
graphe mensuel, date du call pour les tuiles KPI).
Code de sortie 1 s'il y a au moins un écart.
"""
import json
import sys
from collections import defaultdict


def is_sale(c):
    return c.get("v") == "OUI" or (c.get("vir") and c.get("v") != "REMBOURSEMENT")


def sale_month(c):
    return (c.get("sd") or c.get("d") or "")[:7] or "sans date"


def amount(c):
    # closing : p (prix confirmé sinon proposé) avec repli pp ; business : p seulement
    return c.get("p") or c.get("pp") or 0


def by_month(calls, month_of):
    out = defaultdict(lambda: [0, 0])
    for c in calls:
        if is_sale(c):
            m = month_of(c)
            out[m][0] += 1
            out[m][1] += amount(c)
    return out


def main(closing_path, business_path):
    closing = json.load(open(closing_path))["calls"]
    business = json.load(open(business_path))["calls"]
    cl = by_month(closing, sale_month)
    bu = by_month(business, sale_month)
    old = by_month(business, lambda c: c.get("tm") or "sans onglet")
    old_d = by_month(business, lambda c: (c.get("d") or (c.get("tm") or "") + "-01")[:7] or "sans date")
    months = sorted(set(cl) | set(bu) | set(old) | set(old_d))
    print(f"{'mois':<10} {'closing':>14} {'business':>14} {'écart':>12} {'ancien graphe':>16} {'anciens KPI':>16}")
    print(f"{'':<10} {'ventes / CA':>14} {'ventes / CA':>14} {'ventes / CA':>12} {'(mois onglet)':>16} {'(date du call)':>16}")
    ecarts = 0
    for m in months:
        a, b, o, od = cl.get(m, [0, 0]), bu.get(m, [0, 0]), old.get(m, [0, 0]), old_d.get(m, [0, 0])
        dv, dca = b[0] - a[0], b[1] - a[1]
        if dv or dca:
            ecarts += 1
        print(f"{m:<10} {a[0]:>4} / {a[1]:>8,.0f} {b[0]:>4} / {b[1]:>8,.0f} "
              f"{dv:>+4} / {dca:>+7,.0f} {o[0]:>5} / {o[1]:>8,.0f} {od[0]:>5} / {od[1]:>8,.0f}".replace(",", " "))
    ta = sum(v[1] for v in cl.values())
    tb = sum(v[1] for v in bu.values())
    print(f"{'total':<10} {sum(v[0] for v in cl.values()):>4} / {ta:>8,.0f} "
          f"{sum(v[0] for v in bu.values()):>4} / {tb:>8,.0f}".replace(",", " "))
    moved = [c for c in business if is_sale(c) and sale_month(c) != (c.get("tm") or "")]
    print(f"\nventes datées d'un autre mois que leur onglet (nouvelle règle) : {len(moved)}")
    for c in sorted(moved, key=sale_month):
        print(f"  {sale_month(c)}  onglet {c.get('tm')}  call {c.get('d') or '·'}  "
              f"cochée {c.get('sd') or '(repli date du call)'}  {c.get('c') or '·'}  {amount(c):,.0f} €".replace(",", " "))
    nodate = [c for c in business if is_sale(c) and sale_month(c) == "sans date"]
    if nodate:
        print(f"\nATTENTION : {len(nodate)} vente(s) sans date du tout (ni cochage ni call), hors de toute période")
    print("\n" + ("OK : aucun écart entre les deux consoles" if not ecarts
                  else f"ECART sur {ecarts} mois entre closing et business"))
    return 1 if ecarts else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    sys.exit(main(args[0] if args else "closing-data.json",
                  args[1] if len(args) > 1 else "dashboard-data.json"))
