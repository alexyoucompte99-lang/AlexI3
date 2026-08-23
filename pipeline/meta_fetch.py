#!/usr/bin/env python3
"""Récupère la data ads depuis l'API Meta (Insights) et met à jour ads.json.

- spend / impressions / clicks viennent de Meta (source de vérité, quotidien
  agrégé en semaines lundi -> dimanche, depuis 2026-01-01 ; + détail par jour
  des 90 derniers jours dans "days", pour le bilan Telegram quotidien)
- les champs funnel du Sheet (lp_views, call_page_views, calls_booked, ventes,
  ca_ttc, ca_encaisse) sont conservés depuis l'ads.json existant (produit par
  parse_ads_md.py) pour les semaines où ils existent
- en cas d'échec (token expiré, réseau) : ads.json est laissé tel quel et le
  script sort en code 0 avec un avertissement, pour ne pas casser la MAJ auto

Usage: python3 meta_fetch.py [--dry-run]
Config: meta.json  {"app_id", "business_id", "account_id", "token"}
Token: page « Outils » du cas d'utilisation Marketing API de l'app Console I3
Data (ads_read). Court = ~2 h ; longue durée (60 j) via échange avec la clé
secrète : meta_refresh_token.py (à venir).
"""
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ADS = os.path.join(HERE, "ads.json")
SINCE = "2026-01-01"
GRAPH = "https://graph.facebook.com/v21.0"


def api_get(path, token, **params):
    params["access_token"] = token
    url = f"{GRAPH}/{path}?{urllib.parse.urlencode(params)}"
    rows = []
    while url:
        with urllib.request.urlopen(url, timeout=60) as resp:
            out = json.load(resp)
        rows += out.get("data", [])
        url = out.get("paging", {}).get("next")
    return rows


def main():
    dry = "--dry-run" in sys.argv
    try:
        cfg = json.load(open(os.path.join(HERE, "meta.json")))
    except Exception:  # GitHub Actions : config via secrets
        cfg = {"account_id": os.environ.get("META_ACCOUNT", ""),
               "token": os.environ.get("META_TOKEN", "")}
    if not (cfg.get("token") and cfg.get("account_id")):
        print("⚠ pas de config Meta (meta.json ou env) — ads.json inchangé", file=sys.stderr)
        return
    until = dt.date.today().isoformat()
    try:
        days = api_get(
            f"{cfg['account_id']}/insights", cfg["token"],
            fields="spend,impressions,clicks",
            time_increment=1, limit=500,
            time_range=json.dumps({"since": SINCE, "until": until}),
        )
    except Exception as e:
        body = ""
        if hasattr(e, "read"):
            try:
                body = e.read().decode()[:300]
            except Exception:
                pass
        print(f"⚠ Meta fetch échoué ({e}) {body} — ads.json inchangé", file=sys.stderr)
        return  # exit 0 : la MAJ continue avec l'ancien ads.json

    # agrège par semaine lundi -> dimanche
    weekly = {}
    for row in days:
        d = dt.date.fromisoformat(row["date_start"])
        monday = d - dt.timedelta(days=d.weekday())
        w = weekly.setdefault(monday, {"spend": 0.0, "impressions": 0, "clicks": 0})
        w["spend"] += float(row.get("spend") or 0)
        w["impressions"] += int(row.get("impressions") or 0)
        w["clicks"] += int(row.get("clicks") or 0)

    # champs funnel du Sheet, indexés par date de début de semaine
    try:
        old = json.load(open(ADS))
    except Exception:
        old = {"weeks": []}
    sheet_by_start = {w["start"]: w for w in old.get("weeks", [])}
    FUNNEL = ("lp_views", "call_page_views", "calls_booked", "ventes", "ca_ttc", "ca_encaisse")

    weeks = []
    for monday in sorted(weekly):
        m = weekly[monday]
        if not (m["spend"] or m["impressions"]):
            continue
        start = monday.isoformat()
        sheet = sheet_by_start.get(start, {})
        w = {
            "label": monday.strftime("%d/%m") + " → " + (monday + dt.timedelta(days=6)).strftime("%d/%m"),
            "start": start,
            "spend": round(m["spend"], 2),
            "impressions": m["impressions"],
            "clicks": m["clicks"],
        }
        for f in FUNNEL:
            w[f] = sheet.get(f) or 0
        weeks.append(w)

    # détail par jour (90 derniers jours) pour le bilan Telegram quotidien
    cutoff = (dt.date.today() - dt.timedelta(days=90)).isoformat()
    daily = sorted(
        ({"date": row["date_start"], "spend": round(float(row.get("spend") or 0), 2),
          "impressions": int(row.get("impressions") or 0), "clicks": int(row.get("clicks") or 0)}
         for row in days if row["date_start"] >= cutoff),
        key=lambda r: r["date"])

    out = {
        "source": "API Meta Insights (spend/impressions/clics) + tableau ads Google Sheet (funnel)",
        "meta_account": cfg["account_id"],
        "meta_fetched_at": dt.datetime.now().strftime("%d/%m/%Y %H:%M"),
        "weeks": weeks,
        "days": daily,
    }
    print(f"{len(weeks)} semaines Meta ({weeks[0]['start']} -> {weeks[-1]['start']})", file=sys.stderr)
    for w in weeks[-5:]:
        print(f"  {w['label']}  spend={w['spend']:.0f}  booked={w['calls_booked']:.0f}", file=sys.stderr)
    if dry:
        return
    if os.path.exists(ADS):
        os.replace(ADS, ADS + ".bak")
    with open(ADS, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"-> {ADS} (ancien : ads.json.bak)", file=sys.stderr)


if __name__ == "__main__":
    main()
