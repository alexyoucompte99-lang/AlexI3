#!/usr/bin/env python3
"""Inscrits Tally « Inscription évènement Investisseurs 3.0 » (form BzXDDY, event Paris 10/10/2026)
-> event-tally.json (une entrée par soumission). Sert de filet de sécurité à l'onglet EVENT PARIS 2026 :
la ligne Sheet est normalement écrite à la soumission par le script mail (compte contact@), mais si
elle manque, event_sync.py l'ajoute via le pont. Échec réseau = ancien fichier conservé (exit 1)."""
import json, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.tally.so"
FORM = "BzXDDY"
OUT = os.path.join(HERE, "event-tally.json")


def api_key():
    k = os.environ.get("TALLY_API_KEY", "").strip()
    if k:
        return k
    return open(os.path.join(HERE, "..", "scan-patrimoine-thomas", "tally-api-key.txt")).read().strip()


def get(path, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + api_key(), "User-Agent": "curl/8.4.0"})
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception as e:  # noqa
            if i == tries - 1:
                raise
            time.sleep(4 * (i + 1))


def label_key(title):
    t = (title or "").lower()
    if "prénom" in t or "prenom" in t:
        return "prenom"
    if "mail" in t:
        return "email"
    if "nom" in t:
        return "nom"
    if "déjeuner" in t or "dejeuner" in t:
        return "dej"
    if "question" in t:
        return "q"
    return None


def main():
    subs, qs, page = [], {}, 1
    while True:
        d = get(f"/forms/{FORM}/submissions?filter=all&limit=100&page={page}")
        if not qs:
            qs = {q["id"]: label_key(q.get("title")) for q in d.get("questions", [])}
        subs += d.get("submissions", [])
        if not d.get("hasMore"):
            break
        page += 1
    out = []
    for s in subs:
        row = {"id": s["id"], "at": (s.get("submittedAt") or "")[:19], "nom": "", "prenom": "", "email": "", "dej": "", "q": ""}
        for r in s.get("responses", []):
            k = qs.get(r.get("questionId"))
            if k and r.get("answer") is not None:
                row[k] = str(r["answer"]).strip()
        row["email"] = row["email"].lower()
        out.append(row)
    out.sort(key=lambda r: r["at"], reverse=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "subs": out}, f, ensure_ascii=False)
    os.replace(tmp, OUT)
    print(f"event-tally.json : {len(out)} soumissions", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa
        print(f"event_fetch KO ({e}) : ancien event-tally.json conservé", file=sys.stderr)
        sys.exit(1)
