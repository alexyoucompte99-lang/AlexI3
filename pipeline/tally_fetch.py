#!/usr/bin/env python3
"""Récupère les réponses du Tally « Le Scan Patrimoine » (form Np12zj) -> tally.json.

- soumissions complètes ET partielles (filter=all, paginé)
- funnel de drop-off par question (analytics Tally)
- profil A/B/C recalculé avec les mêmes règles que le routage du form
- les soumissions avec source=test sont ignorées (comme les confirmations WhatsApp)

Clé API : env TALLY_API_KEY, sinon ../scan-patrimoine-thomas/tally-api-key.txt.
En cas d'échec réseau, l'ancien tally.json est conservé (sortie code 1, jamais
de fichier cassé) : même philosophie que refresh_data.py.
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.tally.so"
FORM = "Np12zj"

# ordre canonique du form (sert au « où il s'est arrêté » des partielles)
QUESTIONS = [
    ("vOLP4D", "Q1 · Objectif"),
    ("KJDVLV", "Q2 · Réussite à 5 ans"),
    ("LJYPXp", "Q3 · Frein"),
    ("p7WDGB", "Q4 · Posture"),
    ("1Jv9Ml", "Q5 · Déjà essayé"),
    ("MJYELA", "Q6 · Stratégie"),
    ("JJDOLR", "Q7 · Placements"),
    ("g7Z9L4", "Q8 · Épargne / mois"),
    ("yEvJxx", "Q9 · Capital"),
    ("XMY4EY", "Q10 · Priorité /10"),
    ("8P8ZGP", "Prénom"),
    ("0JveLj", "Email"),
    ("yEvbLg", "WhatsApp"),
    ("zrJ7Z0", "Pseudo Instagram"),
]
QID = {k: i for i, (k, _) in enumerate(QUESTIONS)}
HIDDEN_QID = "k7WN5e"

CAPITAL_C = ("Entre 250 000 et 500 000 €", "Plus de 500 000 €")
POSTURE_C = ("Garder la vision, déléguer l’exécution à des gens compétents",
             "Confier l’ensemble à des experts, et garder mon temps pour le reste",
             "Je ne sais pas encore, c’est exactement ce que je veux clarifier")
CAPITAL_A = "Moins de 15 000 €"
EPARGNE_A = ("Moins de 200 €", "Entre 200 et 450 €")


def api_key():
    k = os.environ.get("TALLY_API_KEY", "").strip()
    if k:
        return k
    p = os.path.join(HERE, "..", "scan-patrimoine-thomas", "tally-api-key.txt")
    return open(p).read().strip()


def get(path, tries=4):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(API + path)
            req.add_header("Authorization", "Bearer " + api_key())
            # Cloudflare bloque le user-agent Python par défaut
            req.add_header("User-Agent", "curl/8.4.0")
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:
            err = e
            time.sleep(4 * (i + 1))
    raise RuntimeError(f"API Tally injoignable ({path}) : {err}")


def profil(cap, posture, epargne):
    """Mêmes règles que les blocs de logique du form (routage C puis A, défaut B)."""
    if not cap:
        return ""
    if cap in CAPITAL_C and posture in POSTURE_C:
        return "C"
    if cap == CAPITAL_A and epargne in EPARGNE_A:
        return "A"
    return "B"


def txt(ans):
    """Réponse Tally -> texte lisible (les choix arrivent en liste de libellés)."""
    if ans is None:
        return ""
    if isinstance(ans, list):
        return " · ".join(str(a) for a in ans)
    if isinstance(ans, (int, float)):
        return str(ans)
    return str(ans).strip()


def main():
    out_path = os.path.join(HERE, "tally.json")

    subs_raw, page = [], 1
    while True:
        d = get(f"/forms/{FORM}/submissions?filter=all&page={page}")
        subs_raw += d.get("submissions", [])
        if not d.get("hasMore"):
            break
        page += 1

    drop = get(f"/forms/{FORM}/analytics/drop-off?period=all")

    subs = []
    for s in subs_raw:
        a, hidden = {}, {}
        for r in s.get("responses", []):
            qid = r.get("questionId")
            if qid == HIDDEN_QID:
                if isinstance(r.get("answer"), dict):
                    hidden = r["answer"]
                continue
            if qid in QID:
                a[qid] = txt(r.get("answer"))
        source = str(hidden.get("source") or "").strip()
        if source.lower() == "test":
            continue
        answered = [QID[q] for q in a if a[q] != ""]
        subs.append({
            "id": s["id"],
            "at": s.get("submittedAt") or "",
            "done": bool(s.get("isCompleted")),
            "prenom": a.get("8P8ZGP", ""),
            "email": a.get("0JveLj", "").lower(),
            "tel": a.get("yEvbLg", ""),
            "insta": a.get("zrJ7Z0", ""),
            "source": source,
            "pseudo": str(hidden.get("pseudo") or "").strip(),
            "profil": profil(a.get("yEvJxx"), a.get("p7WDGB"), a.get("g7Z9L4")),
            "last": max(answered) if answered else -1,
            "nrep": len(answered),
            "a": a,
        })
    subs.sort(key=lambda s: s["at"], reverse=True)

    st = drop.get("stats", {})
    out = {
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "questions": [{"id": k, "label": lbl} for k, lbl in QUESTIONS],
        "stats": {"visitors": st.get("totalVisitors", 0),
                  "starts": st.get("formStarts", 0),
                  "completes": st.get("formCompletes", 0),
                  "avg_seconds": st.get("completionTimeInSeconds")},
        "dropoff": [{"t": x.get("title", ""), "views": x.get("views", 0),
                     "answers": x.get("answers", 0), "drops": x.get("drops", 0)}
                    for x in drop.get("data", [])],
        "subs": subs,
    }
    tmp = out_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f, ensure_ascii=False)
    os.replace(tmp, out_path)
    print(f"tally.json OK : {len(subs)} soumission(s) "
          f"({sum(1 for s in subs if s['done'])} complète(s))", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"tally_fetch KO : {e} (ancien tally.json conservé)", file=sys.stderr)
        sys.exit(1)
