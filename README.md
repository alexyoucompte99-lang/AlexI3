# AlexI3

Pages statiques protégées par code (contenu chiffré AES-256, déchiffré dans le navigateur).
Générées automatiquement, ne pas éditer à la main.

## Pipeline (dossier `pipeline/`)

Runbook complet : `/Users/alex/Alex/thomas-dashboard/README.md`. Enchaînement du workflow
`.github/workflows/refresh.yml` (toutes les ~15 min) : `parse_xlsx.py` puis `sales_ledger.py`
(registre `.sales-ledger.json`), puis `aggregate.py` + `build.py` (console business, `index.html`)
et `aggregate_closing.py` + `build.py` (console closing, `closing/index.html`).

Règle commune aux deux consoles depuis le 01/09/2026 (console business migrée le 13/09/2026) :
**date de vente = jour du cochage** dans la console closing (champ `sd` posé par
`sales_ledger.py`), repli sur la date du call pour les ventes antérieures au registre.
Contrôle : `python3 pipeline/check_ventes.py closing-data.json dashboard-data.json`
(ventes et CA par mois des deux consoles, code de sortie 1 s'il y a un écart).
