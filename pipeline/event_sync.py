#!/usr/bin/env python3
"""Filet de sécurité de l'onglet Sheet « Event Paris 2026 » : toute soumission Tally (event-tally.json)
absente du Sheet (data.json["event"], comparaison par mail puis id Tally) est ajoutée via le pont
(what=event_add). Le script mail (compte contact@) écrit normalement la ligne à la seconde ; ici on
rattrape les ratés. Mail auto = « ? à vérifier » pour les inscriptions postérieures à la mise en
service (09/09/2026 11:30), « Justine (manuel) » avant. Env : BRIDGE_URL / BRIDGE_KEY (sinon bridge.json).
Usage : python3 event_sync.py data.json [--dry]"""
import json, os, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
AUTO_SINCE = "2026-09-09T09:30:00"  # UTC


def bridge():
    u, k = os.environ.get("BRIDGE_URL", "").strip(), os.environ.get("BRIDGE_KEY", "").strip()
    if u and k:
        return u, k
    b = json.load(open(os.path.join(HERE, "bridge.json")))
    return b["url"], b["key"]


def fr(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]} {iso[11:16]}" if len(iso) >= 16 else iso


def main(data_path, dry=False):
    d = json.load(open(data_path))
    rows = d.get("event") or []
    tal = json.load(open(os.path.join(HERE, "event-tally.json"))).get("subs", [])
    mails = {(r.get("email") or "").lower() for r in rows if r.get("email")}
    ids = {r.get("tally_id") for r in rows if r.get("tally_id")}
    missing, seen = [], set()
    for s in sorted(tal, key=lambda x: x["at"]):  # plus ancienne soumission d'abord
        em = s["email"]
        if (em and em in mails) or s["id"] in ids or (em and em in seen) or not em:
            continue
        seen.add(em)
        missing.append({"nom": s["nom"], "prenom": s["prenom"], "email": em, "membre": 1, "invite": "", "invite_nom": "",
                        "inscrit_le": fr(s["at"]), "dej": s["dej"], "question": s["q"],
                        "mail_auto": "? à vérifier" if s["at"] >= AUTO_SINCE else "Justine (manuel)",
                        "source": "Tally (sync)", "tally_id": s["id"], "commentaire": ""})
    print(f"event_sync : {len(rows)} lignes Sheet, {len(tal)} soumissions Tally, {len(missing)} à ajouter", file=sys.stderr)
    if not missing or dry:
        if dry:
            print(json.dumps(missing, ensure_ascii=False, indent=1))
        return
    url, key = bridge()
    body = json.dumps({"key": key, "what": "event_add", "rows": missing}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "text/plain"})
    print(urllib.request.urlopen(req, timeout=120).read().decode()[:300], file=sys.stderr)


if __name__ == "__main__":
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else "data.json", "--dry" in sys.argv)
    except Exception as e:  # noqa
        print(f"event_sync KO : {e}", file=sys.stderr)
        sys.exit(1)
