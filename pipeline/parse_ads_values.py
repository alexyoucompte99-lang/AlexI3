#!/usr/bin/env python3
"""Parse le tableau ads renvoyé par le pont Apps Script (getDisplayValues,
tableau 2D de chaînes) en ads.json — même logique que parse_ads_md.py.

Usage: python3 parse_ads_values.py ads_values.json ads.json
"""
import datetime as dt
import json
import re
import sys

METRICS = {
    "amount spent": "spend",
    "impressions": "impressions",
    "clicks": "clicks",
    "page views": "lp_views",
    "vue de page call": "call_page_views",
    "call booked": "calls_booked",
    "ventes totales": "ventes",
    "chiffre d'affaires ttc": "ca_ttc",
    "chiffre d'affaires encaissé ttc": "ca_encaisse",
    "chiffre d'affaires encaisse ttc": "ca_encaisse",
}


def parse_num(s):
    if not s:
        return None
    s = s.replace("€", "").replace("%", "").replace("\xa0", "").replace(" ", "")
    s = s.replace(" ", "").replace(",", ".")
    m = re.match(r"^-?\d+(\.\d+)?$", s)
    return float(s) if m else None


def main(in_path, out_path):
    rows = [[str(c).strip() for c in r] for r in json.load(open(in_path))]

    net_row = None
    for r in rows:
        if sum(1 for c in r if c.upper() == "TOTAL") >= 3:
            net_row = r
            break
    if not net_row:
        raise SystemExit("ligne FACEBOOK/YOUTUBE/ORGANIQUE/TOTAL introuvable")
    total_cols = [i for i, c in enumerate(net_row) if c.upper() == "TOTAL"]

    week_row = None
    for r in rows:
        if sum(1 for c in r if re.search(r"\bDu\b", c) or "juin" in c.lower()) >= 3:
            week_row = r
            break

    def label_for(col):
        if not week_row:
            return ""
        for j in range(col, max(-1, col - 5), -1):
            if j < len(week_row) and week_row[j]:
                return week_row[j]
        return ""

    metric_rows = {}
    for r in rows:
        if not r:
            continue
        key = r[0].lower()
        for mk, field in METRICS.items():
            if key.startswith(mk):
                if field not in metric_rows:
                    metric_rows[field] = r
                break

    def start_from_label(lab):
        m = re.search(r"[Dd]u\s+(\d{1,2})/(\d{1,2})/(\d{2,4})", lab)
        if not m:
            return None
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return dt.date(y, mo, d)
        except ValueError:
            return None

    first_start = None
    for col in total_cols:
        s = start_from_label(label_for(col))
        if s:
            first_start = s
            break
    if not first_start:
        first_start = dt.date(2026, 5, 4)

    weeks = []
    for wi, col in enumerate(total_cols):
        def val(field):
            r = metric_rows.get(field)
            if not r or col >= len(r):
                return None
            return parse_num(r[col])
        start = first_start + dt.timedelta(days=7 * wi)
        resync = start_from_label(label_for(col))
        if resync:
            start = resync
        w = {
            "label": start.strftime("%d/%m") + " → " + (start + dt.timedelta(days=6)).strftime("%d/%m"),
            "start": start.isoformat(),
            "spend": val("spend") or 0,
            "impressions": val("impressions") or 0,
            "clicks": val("clicks") or 0,
            "lp_views": val("lp_views") or 0,
            "call_page_views": val("call_page_views") or 0,
            "calls_booked": val("calls_booked") or 0,
            "ventes": val("ventes") or 0,
            "ca_ttc": val("ca_ttc") or 0,
            "ca_encaisse": val("ca_encaisse") or 0,
        }
        if w["spend"] or w["impressions"] or w["calls_booked"]:
            weeks.append(w)

    out = {"source": "Tableau ads Google Sheet (via pont Apps Script)", "weeks": weeks}
    with open(out_path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"{len(weeks)} semaines -> {out_path}", file=sys.stderr)
    for w in weeks[-3:]:
        print(f"  {w['label']}  spend={w['spend']:.0f}  booked={w['calls_booked']:.0f}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
