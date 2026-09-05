#!/usr/bin/env python3
"""Récupère le pipeline commercial du CRM Valar (Google Sheet, via le point
d'accès Apps Script à jeton de l'app Valar Asset Manager) -> valar.json.

Sert à l'onglet « Leads Valar » de la console closing : les closers I3 voient
où en sont les prospects qu'ils ont envoyés en appel chez Valar (R1, R2, signé,
no-show, à relancer, non abouti).

Accès : env VALAR_URL + VALAR_TOKEN, sinon private.json (VALAR_URL/VALAR_TOKEN)
à côté du script. En cas d'échec réseau, l'ancien valar.json est conservé
(code de sortie 1, jamais de fichier cassé) : même philosophie que tally_fetch.
"""
import datetime as dt
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

# onglet du point d'accès -> étape lisible côté console
STAGES = [
    ("r1", "r1"),
    ("r2", "r2"),
    ("clients", "client"),
    ("noShowR1", "noshow"),
    ("aSuivre", "asuivre"),
    ("nonAbouti", "nonabouti"),
]


def access():
    url = os.environ.get("VALAR_URL", "").strip()
    tok = os.environ.get("VALAR_TOKEN", "").strip()
    if not (url and tok):
        try:
            p = json.load(open(os.path.join(HERE, "private.json")))
            url = url or (p.get("VALAR_URL") or "").strip()
            tok = tok or (p.get("VALAR_TOKEN") or "").strip()
        except Exception:
            pass
    return url, tok


def norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", s).strip().lower()


def cell(row, *prefixes):
    """Première cellule non vide dont l'en-tête (normalisé) commence par un des préfixes."""
    for pre in prefixes:
        for k, v in row.items():
            v = str(v or "").strip()
            if v and norm(k).startswith(pre):
                return v
    return ""


DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})(?:\s+(\d{1,2}):(\d{2}))?")


def date_iso(v):
    """« 04/05/2026 » ou « 29/06/2026 21:00:00 » -> (« 2026-05-04 », « 21:00 »).
    Texte libre (« En attente date R2 ») -> (None, texte)."""
    v = (v or "").strip()
    if not v:
        return None, ""
    m = DATE_RE.match(v)
    if not m:
        return None, v
    y = int(m.group(3))
    y = 2000 + y if y < 100 else y
    try:
        d = dt.date(y, int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None, v
    hh = f"{int(m.group(4)):02d}:{m.group(5)}" if m.group(4) else ""
    return d.isoformat(), hh


def euros(v):
    v = (v or "").strip()
    if not v:
        return 0
    n = re.sub(r"[^\d,.\-]", "", v).replace(".", "").replace(",", ".")
    try:
        return round(float(n))
    except ValueError:
        return 0


def phone_digits(v):
    d = re.sub(r"\D", "", v or "")
    if d.startswith("0") and len(d) == 10:
        d = "33" + d[1:]
    return d


def lead_of(row, stage):
    nom = cell(row, "prenom - nom", "nom")
    if not nom:
        return None
    r1, r1h = date_iso(cell(row, "date r1"))
    r2, r2h = date_iso(cell(row, "date r2"))
    r3, r3h = date_iso(cell(row, "date r3"))
    sign, _ = date_iso(cell(row, "date signature"))
    perte, _ = date_iso(cell(row, "date de perte", "date du non abouti"))
    rel, _ = date_iso(cell(row, "relance le", "date a relancer"))
    return {
        "id": cell(row, "_id") or nom,
        "n": nom,
        "stage": stage,
        "statut": cell(row, "statut"),
        "src": cell(row, "source"),
        "mail": cell(row, "mail").lower(),
        "tel": phone_digits(cell(row, "numero")),
        "r1": r1, "r1h": r1h, "r2": r2, "r2h": r2h, "r3": r3, "r3h": r3h,
        # texte libre à la place d'une date (« En attente date R2 »)
        "r2txt": r2h if r2 is None else "",
        "gf": cell(row, "gf assigne"),
        "preq": cell(row, "pre-qualification"),
        "com": cell(row, "commentaire suivi hebdo", "commentaires suivi hebdo", "commentaire du r1", "commentaire"),
        "hon": euros(cell(row, "honoraires (montant)", "honoraire montant", "honoraires", "montant honoraire encaisse")),
        "enc": euros(cell(row, "montant encours sous gestion")),
        "enca": euros(cell(row, "montant encours en attente")),
        "sign": sign,
        "perte": perte,
        "raison": cell(row, "raison non abouti", "perdu en"),
        "rel": rel,
        "o2s": cell(row, "fiche client o2s", "client dans o2s", "prospect / client dans o2s", "profil o2s"),
    }


def main(out_path):
    url, tok = access()
    if not (url and tok):
        print("valar_fetch : VALAR_URL / VALAR_TOKEN absents", file=sys.stderr)
        return 1
    full = url + ("&" if "?" in url else "?") + "token=" + urllib.parse.quote(tok)
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": "console-i3/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = json.loads(r.read().decode("utf-8"))
            break
        except Exception as e:  # noqa: BLE001
            last = e
            raw = None
    if raw is None or "onglets" not in raw:
        print(f"valar_fetch KO : {last or raw}", file=sys.stderr)
        return 1

    leads = []
    for key, stage in STAGES:
        for row in raw["onglets"].get(key) or []:
            l = lead_of(row, stage)
            if l:
                leads.append(l)

    out = {
        "fetched_at": dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "genere_le": raw.get("genereLe"),
        "leads": leads,
    }
    tmp = out_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f, ensure_ascii=False)
    os.replace(tmp, out_path)
    by = {}
    for l in leads:
        by[l["stage"]] = by.get(l["stage"], 0) + 1
    print(f"valar.json : {len(leads)} leads {by}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "valar.json")))
