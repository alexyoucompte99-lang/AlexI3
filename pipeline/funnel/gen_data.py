#!/usr/bin/env python3
"""Genere data-block.js (RELEVE / SOURCES_AT / DAYS / PIX_FROM / OLD / NEW) pour la console funnel v2.

Usage : python3 gen_data.py releves/releve_raw_AAAA-MM-JJ.json "JJ mois AAAA" [--prev=releves/data-block_avant.js]
        python3 gen_data.py --pixel-from-prev --prev=data-block.js   (pas de nouveau releve pixel : on garde le precedent)

Sources :
  - releve pixel brut (snippet releve_events_manager.js, ~30 jours glissants), fusionne avec le precedent
    data-block (backfill des jours plus anciens, jamais ecrases par des zeros)
  - sources/daily_sources.json (fetch_sources.py) : closing (Sheet) et ads (Meta) par jour depuis le 1er janvier
Modele :
  DAYS = tous les jours du 1er janvier de l'annee en cours a aujourd'hui
  OLD / NEW = { pv, v{0..95}, pot, qual, disq, rdv  (pixel ; null avant PIX_FROM = pas de donnee),
                beh{...} (NEW seulement, pixel),
                ads{spend, clicks, link, lpv, vv}, cl{booked, present, noshow, reprog, annule, vente, ca, followup, resa} }
"""
import json, re, sys, os, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:] if not a.startswith('--')]
opts = {a.split('=', 1)[0]: (a.split('=', 1)[1] if '=' in a else True) for a in sys.argv[1:] if a.startswith('--')}
prev_path = opts.get('--prev', os.path.join(HERE, 'data-block.js'))
today = dt.date.today()
YEAR_START = dt.date(today.year, 1, 1)
DAYS = [(YEAR_START + dt.timedelta(days=i)).isoformat() for i in range((today - YEAR_START).days + 1)]
N = len(DAYS)
PCTS = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95]
BEH_KEYS = ['t30', 't1', 't2', 't3', 't5', 't10', 'play', 'v60', 'pitch', 'fs', 'cta', 'ctaF', 'ctaB', 's25', 's50', 's75', 's90',
            'secThomas', 'secEtapes', 'secCtaF', 'secProof', 'secTemoin', 'tvClick', 'tGhislain', 'tLouis', 'tKim', 'tSophie', 'tLodois', 'exit', 'footer', 'merci']
CORE = ['pv', 'pot', 'qual', 'disq', 'rdv', 'sched']

def parse_block(path):
    """Lit un data-block.js (formats v0 var D, v1 OLD/NEW 33 jours, v2 OLD/NEW annee) -> dict normalise {DAYS, RELEVE, OLD, NEW}."""
    vars_ = {}
    for line in open(path, encoding='utf-8').read().split('\n'):
        m = re.match(r'var (\w+) = (.*);\s*$', line.strip())
        if m:
            try: vars_[m.group(1)] = json.loads(m.group(2))
            except ValueError: pass
    if 'DAYS' not in vars_: return None
    out = {'DAYS': vars_['DAYS'], 'RELEVE': vars_.get('RELEVE')}
    if 'OLD' in vars_ and 'NEW' in vars_:
        out['OLD'], out['NEW'] = vars_['OLD'], vars_['NEW']
    elif 'D' in vars_:
        D = vars_['D']
        out['OLD'] = {k: D[k] for k in CORE + ['v']}
        out['NEW'] = {'beh': D.get('nlp', {})}
    else:
        return None
    return out

prev = parse_block(prev_path) if os.path.exists(prev_path) else None

# ---------- pixel : on part d'un dictionnaire jour -> valeur (None = pas de donnee)
def series_from(block_days, arr):
    return {d: (arr[i] if i < len(arr) else None) for i, d in enumerate(block_days)} if arr else {}

pix = {'OLD': {k: {} for k in CORE} | {'v': {p: {} for p in PCTS}}, 'NEW': {k: {} for k in CORE} | {'v': {p: {} for p in PCTS}, 'beh': {k: {} for k in BEH_KEYS}}}
def ingest(block_days, src, into, is_prev):
    for k in CORE:
        if k in src: into[k].update({d: v for d, v in series_from(block_days, src[k]).items() if v is not None})
    for p in PCTS:
        arr = (src.get('v') or {}).get(str(p))
        if arr: into['v'][p].update({d: v for d, v in series_from(block_days, arr).items() if v is not None})
    if 'beh' in into and src.get('beh'):
        for k in BEH_KEYS:
            arr = src['beh'].get(k)
            if arr: into['beh'][k].update({d: v for d, v in series_from(block_days, arr).items() if v is not None})

if prev:
    ingest(prev['DAYS'], prev.get('OLD', {}), pix['OLD'], True)
    ingest(prev['DAYS'], prev.get('NEW', {}), pix['NEW'], True)
    print('backfill pixel depuis', prev_path, ':', prev['DAYS'][0], '->', prev['DAYS'][-1])

releve_label = prev.get('RELEVE') if prev else None
if args:
    raw = json.load(open(args[0]))
    releve_label = args[1] if len(args) > 1 else today.strftime('%-d %B %Y')
    first_nonzero = next((i for i, v in enumerate(raw['OLD']['pv']) if v > 0), 0)
    cutoff = first_nonzero + 1  # 1er jour couvert = partiel -> on garde l'ancien
    rdays = raw['DAYS'][cutoff:]
    def cut(arr): return arr[cutoff:]
    for who in ('OLD', 'NEW'):
        src = {k: cut(raw[who][k]) for k in CORE}
        src['v'] = {str(p): cut(raw[who]['v'][str(p)]) for p in PCTS}
        if who == 'NEW': src['beh'] = {k: cut(raw['NEW']['beh'][k]) for k in BEH_KEYS if k in raw['NEW']['beh']}
        ingest(rdays, src, pix[who], False)
    print('releve pixel', args[0], ': couverture', rdays[0], '->', rdays[-1], '(le 1er jour du brut, partiel, est ignore)')

covered = sorted(d for d in pix['OLD']['pv'] if d >= DAYS[0])
PIX_FROM = covered[0] if covered else None
print('couverture pixel :', PIX_FROM, '->', covered[-1] if covered else None, '(', len(covered), 'jours )')

def arr_of(dic, default_none=True):
    return [dic.get(d, None if default_none else 0) if d in dic else (None if default_none else 0) for d in DAYS]
def pix_arr(dic):
    # null avant PIX_FROM ou si jamais releve ; 0 si couvert mais absent (serie vide ce jour-la)
    return [(dic.get(d, 0) if (PIX_FROM and d >= PIX_FROM and d in pix['OLD']['pv']) else None) for d in DAYS]

OLD = {k: pix_arr(pix['OLD'][k]) for k in CORE}
OLD['v'] = {str(p): pix_arr(pix['OLD']['v'][p]) for p in PCTS}
NEW = {k: pix_arr(pix['NEW'][k]) for k in CORE}
NEW['v'] = {str(p): pix_arr(pix['NEW']['v'][p]) for p in PCTS}
NEW['beh'] = {k: pix_arr(pix['NEW']['beh'][k]) for k in BEH_KEYS}

# ---------- sources closing + ads (0 = pas d'activite ce jour-la)
SOURCES_AT = None
src_path = os.path.join(HERE, 'sources', 'daily_sources.json')
ADS_KEYS = ['spend', 'clicks', 'link', 'lpv', 'vv']
CL_KEYS = ['booked', 'present', 'noshow', 'reprog', 'annule', 'vente', 'ca', 'followup', 'rel', 'resa']
if os.path.exists(src_path):
    S = json.load(open(src_path))
    SOURCES_AT = S.get('fetched_at')
    for who, key in (('OLD', 'old'), ('NEW', 'new')):
        tgt = OLD if who == 'OLD' else NEW
        tgt['ads'] = {k: [round((S['ads'][key].get(d) or {}).get(k, 0), 2) if k == 'spend' else int((S['ads'][key].get(d) or {}).get(k, 0)) for d in DAYS] for k in ADS_KEYS}
        tgt['cl'] = {k: [int((S['closing'][key].get(d) or {}).get(k, 0)) for d in DAYS] for k in CL_KEYS}
    print('sources closing/ads du', SOURCES_AT)
else:
    print('ATTENTION : sources/daily_sources.json absent (lancer fetch_sources.py) -> ads/cl a zero')
    for tgt in (OLD, NEW):
        tgt['ads'] = {k: [0] * N for k in ADS_KEYS}
        tgt['cl'] = {k: [0] * N for k in CL_KEYS}

block = 'var RELEVE = ' + json.dumps(releve_label, ensure_ascii=False) + ';\n'
block += 'var SOURCES_AT = ' + json.dumps(SOURCES_AT, ensure_ascii=False) + ';\n'
block += 'var PIX_FROM = ' + json.dumps(PIX_FROM) + ';\n'
block += 'var DAYS = ' + json.dumps(DAYS) + ';\n'
block += 'var OLD = ' + json.dumps(OLD, separators=(',', ':')) + ';\n'
block += 'var NEW = ' + json.dumps(NEW, separators=(',', ':')) + ';\n'
open(os.path.join(HERE, 'data-block.js'), 'w', encoding='utf-8').write(block)
print('data-block.js ecrit :', N, 'jours du', DAYS[0], 'au', DAYS[-1], '| taille', len(block) // 1024, 'Ko')
nz = lambda a: sum(x for x in a if x)
print('controle OLD : pv', nz(OLD['pv']), 'rdv', nz(OLD['rdv']), 'lpv', nz(OLD['ads']['lpv']), 'booked', nz(OLD['cl']['booked']), 'present', nz(OLD['cl']['present']), 'ventes', nz(OLD['cl']['vente']))
print('controle NEW : pv', nz(NEW['pv']), 'play', nz(NEW['beh']['play']), 'lpv', nz(NEW['ads']['lpv']), 'booked', nz(NEW['cl']['booked']), 'resa', nz(NEW['cl']['resa']), 'sched', nz(NEW['sched']))
