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

## API Conversions Meta (14/09/2026) : Schedule côté serveur

Constat du 14/09 : les 4 Schedule navigateur de la semaine sont bien arrivés chez Meta, mais le BM
n'en attribuait que 2 aux pubs (cookies perdus, arrivée sans fbclid, réservation faite hors LP).
Correctif :
- la page merci (repo lp-investisseurs30) fait de la correspondance avancée manuelle (e-mail, nom,
  tél dans `fbq('init')`) et pousse chaque réservation dans l'onglet Sheet « CAPI Schedule » via le
  pont (`what=capi_schedule`, pont v21, clé publique) : event_id du Schedule navigateur, e-mail, tél,
  cookies _fbp/_fbc, user agent ;
- `pipeline/capi_send.py` (appelé par refresh.yml toutes les 15 min) renvoie ces réservations à Meta
  par l'API Conversions (même event_id, donc dédoublonné avec le navigateur), plus les réservations du
  calendrier « Appel Diagnostic - Club » présentes dans le Sheet sans passage par la page merci
  (e-mail + tél + nom, event_id dérivé, à partir du 15/09). Registre `.capi-sent.json` (ids hachés).
- Activation : secret `META_CAPI_TOKEN` (token API Conversions du pixel 1625394888920444, à générer
  dans Events Manager > Paramètres > API Conversions > Générer un token d'accès). Sans secret : no-op.
- Test manuel : `python capi_send.py investisseurs30.xlsx data.json ../.capi-sent.json --dry-run`
  (ou `--test-code TESTxxxx` pour voir l'évènement dans Events Manager > Évènements de test).
