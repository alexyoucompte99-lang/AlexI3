#!/usr/bin/env python3
"""Injecte dashboard-data.json dans template.html -> dashboard.html.

Substitue aussi les placeholders privés __NOM__ (codes d'accès, numéros
WhatsApp, pont de données) depuis private.json (à côté du script) ou, à
défaut, depuis les variables d'environnement (GitHub Actions).
"""
import json
import os
import sys

PRIVATE_KEYS = ["ALEX_CODE", "PILOTAGE_CODE", "FUNNEL_CODE", "WA_THOMAS", "WA_ALEX",
                "BRIDGE_URL", "BRIDGE_KEY"]

data_path = sys.argv[1] if len(sys.argv) > 1 else "dashboard-data.json"
tpl_path = sys.argv[2] if len(sys.argv) > 2 else "template.html"
out_path = sys.argv[3] if len(sys.argv) > 3 else "dashboard.html"

with open(data_path) as f:
    data = json.load(f)
with open(tpl_path) as f:
    tpl = f.read()

blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
out = tpl.replace("__DATA_JSON__", blob)
assert "__DATA_JSON__" not in out

here = os.path.dirname(os.path.abspath(__file__))

# onglet Funnel : fragments produits par funnel_fragment.py (CSS limité à #fxRoot,
# markup + JS de la console funnel). Absents = onglet vide plutôt qu'un build cassé.
for ph, fname in (("__FUNNEL_CSS__", "funnel-fragment.css"),
                  ("__FUNNEL_HTML__", "funnel-fragment.html")):
    if ph not in out:
        continue
    path = os.path.join(here, fname)
    try:
        frag = open(path, encoding="utf-8").read()
    except OSError:
        frag = ""
        print(f"ATTENTION : {fname} absent, onglet Funnel vide", file=sys.stderr)
    out = out.replace(ph, frag)
try:
    private = json.load(open(os.path.join(here, "private.json")))
except Exception:
    private = {}
for k in PRIVATE_KEYS:
    out = out.replace(f"__{k}__", private.get(k) or os.environ.get(k, ""))

with open(out_path, "w") as f:
    f.write(out)
print(f"OK -> {out_path} ({len(out)//1024} KB)")
