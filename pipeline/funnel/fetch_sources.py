#!/usr/bin/env python3
"""Recupere les sources hors pixel pour la console funnel :
  - closing (Sheet « Tracking - Investisseurs 3.0 », onglets Suivi Closing mensuels) via le pont Apps Script
    -> sources/investisseurs30.xlsx -> parse_xlsx.py (thomas-dashboard) -> sources/data_closing.json
  - ads Meta (API Insights, niveau campagne, quotidien, depuis le 1er janvier) -> sources/ads_daily_raw.json
Puis agrege par jour et par funnel dans sources/daily_sources.json :
  closing[funnel][jour] = {booked, present, noshow, reprog, annule, vente, ca, followup, rel, resa}
    booked = au jour du call ; resa = au jour de la reservation (comparable au pixel)
  ads[funnel][jour]     = {spend, clicks, link, lpv, vv}
Funnel « new » = calendrier iClosed « Appel Diagnostic - Club Investisseurs 3.0 » (calls) et campagnes
dont le nom matche NEW_CAMPAIGN_RE (ads) ; funnel « old » = le reste (calls des autres calendriers hors onglets webinaire, toutes les campagnes
hors Webinaire : VSL + retargeting). Les campagnes Webinaire sont ignorees.
Usage : python3 fetch_sources.py [--no-ads] [--no-closing]
"""
import json, re, sys, os, base64, time, datetime as dt, urllib.request, urllib.parse, subprocess, collections

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'sources')
# En local : configs et parse_xlsx.py dans thomas-dashboard. Dans GitHub Actions : tout vient de
# variables d'environnement (BRIDGE_URL/BRIDGE_KEY, META_TOKEN/META_ACCOUNT) et PARSE_XLSX pointe
# vers pipeline/parse_xlsx.py du repo public AlexI3 (checkout dans le workflow).
TD = os.environ.get('TD_DIR', '/Users/alex/Alex/thomas-dashboard')
PARSE_XLSX = os.environ.get('PARSE_XLSX', os.path.join(TD, 'parse_xlsx.py'))
os.makedirs(SRC, exist_ok=True)
NEW_CAMPAIGN_RE = re.compile(r'strat[ée]gie.?priv[ée]e|nouvelle.?lp|lp.?vsl.?v2|lp.?v2|club|new.?vsl', re.I)
NEW_CALENDAR_RE = re.compile(r'appel diagnostic\s*-\s*club', re.I)
WEBI_CAMPAIGN_RE = re.compile(r'webi', re.I)
SINCE = '2026-01-01'

def fetch_closing():
    burl, bkey = os.environ.get('BRIDGE_URL'), os.environ.get('BRIDGE_KEY')
    if not (burl and bkey):
        b = json.load(open(os.path.join(TD, 'bridge.json')))
        burl, bkey = b['url'], b['key']
    url = burl + '?' + urllib.parse.urlencode({'key': bkey, 'what': 'closing'})
    raw = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'curl/8'}), timeout=180).read()
    txt = raw.decode('ascii', 'ignore').strip()
    try:
        j = json.loads(txt); b64 = j.get('xlsx') or j.get('b64') or j.get('data')
    except Exception:
        b64 = txt
    data = base64.b64decode(b64)
    assert data[:2] == b'PK', 'reponse pont inattendue : ' + repr(data[:40])
    xlsx = os.path.join(SRC, 'investisseurs30.xlsx')
    open(xlsx, 'wb').write(data)
    out = os.path.join(SRC, 'data_closing.json')
    subprocess.run([sys.executable, PARSE_XLSX, xlsx, out], check=True, stdout=subprocess.DEVNULL)
    print('closing : xlsx', len(data) // 1024, 'Ko ->', out)

def fetch_ads():
    token, account = os.environ.get('META_TOKEN'), os.environ.get('META_ACCOUNT')
    if not (token and account):
        cfg = json.load(open(os.path.join(TD, 'meta.json')))
        token, account = cfg['token'], cfg['account_id']
    until = dt.date.today().isoformat()
    params = {'access_token': token, 'level': 'campaign', 'fields': 'campaign_id,campaign_name,spend,impressions,clicks,actions',
              'time_increment': 1, 'time_range': json.dumps({'since': SINCE, 'until': until}), 'limit': 500}
    url = 'https://graph.facebook.com/v21.0/' + account + '/insights?' + urllib.parse.urlencode(params)
    rows = []
    while url:
        r = json.load(urllib.request.urlopen(url, timeout=120))
        rows += r.get('data', [])
        url = (r.get('paging') or {}).get('next')
        time.sleep(0.2)
    out = []
    for row in rows:
        am = {a['action_type']: float(a['value']) for a in row.get('actions', []) or []}
        out.append({'d': row['date_start'], 'cid': row['campaign_id'], 'camp': row['campaign_name'], 'spend': float(row.get('spend', 0)),
                    'imp': int(row.get('impressions', 0)), 'clicks': int(row.get('clicks', 0)), 'link': am.get('link_click', 0),
                    'lpv': am.get('landing_page_view', 0), 'vv': am.get('video_view', 0)})
    json.dump(out, open(os.path.join(SRC, 'ads_daily_raw.json'), 'w'))
    print('ads : ', len(out), 'lignes campagne x jour, du', min(o['d'] for o in out), 'au', max(o['d'] for o in out))

def aggregate():
    closing = {'old': collections.defaultdict(lambda: collections.Counter()), 'new': collections.defaultdict(lambda: collections.Counter())}
    d = json.load(open(os.path.join(SRC, 'data_closing.json')))
    n_webi = n_dup = 0
    calls = [c for c in d['calls'] if c.get('date') and not c.get('webi')]
    n_webi = sum(1 for c in d['calls'] if c.get('webi'))
    # index (mail / telephone) par mois d'onglet, pour reperer les doublons entre onglets
    def tabm(c): return '%04d-%02d' % (c.get('year') or int(c['date'][:4]), c.get('month') or int(c['date'][5:7]))
    def ids(c):
        out = set()
        m = (c.get('mail') or '').strip().lower(); t = (c.get('phone') or '').strip()
        if m: out.add('m:' + m)
        if t: out.add('t:' + t)
        return out
    by_tab = collections.defaultdict(set)
    for c in calls:
        by_tab[tabm(c)] |= ids(c)
    for c in calls:
        f = 'new' if NEW_CALENDAR_RE.search(c.get('source') or '') else 'old'
        tab_month = tabm(c)
        key = c['date']
        if c['date'][:7] < tab_month:
            # regle « onglet du mois » (comme la console closing et le recap Suivi DATA) : une ligne datee d'un mois
            # anterieur a son onglet (relance / follow-up close ce mois-ci) est comptee au 1er jour du mois de l'onglet
            key = tab_month + '-01'
        elif c['date'][:7] > tab_month:
            # ligne datee d'un mois posterieur a son onglet (call booke pour le mois suivant) : si la meme personne
            # figure dans l'onglet du mois de la date, c'est un doublon -> ignoree ; sinon comptee a sa date
            if ids(c) & by_tab.get(c['date'][:7], set()):
                n_dup += 1
                continue
        if key < SINCE:
            continue
        day = closing[f][key]
        day['booked'] += 1
        if key != c['date']: day['rel'] += 1
        # « resa » : le meme call, mais compte au jour ou il a ete RESERVE (colonne date de
        # reservation du Sheet). C'est la seule mesure comparable au pixel (evenement Schedule /
        # invitee_meeting_scheduled, envoye au moment de la reservation) : « booked » compte au
        # jour du call, donc un call reserve le 28 pour le 4 du mois suivant sort de la fenetre.
        # Repli sur la date du call quand la colonne est vide (frequent sur l'ancien funnel).
        bd = (c.get('booking_date') or '')[:10] or key
        if bd >= SINCE: closing[f][bd]['resa'] += 1
        su = (c.get('show_up') or '').upper()
        if su == 'OUI': day['present'] += 1
        elif su == 'NON': day['noshow'] += 1
        elif su.startswith('REPROG'): day['reprog'] += 1
        elif su.startswith('ANNUL'): day['annule'] += 1
        vente = (c.get('vente') or '').upper() == 'OUI' or bool(c.get('virement'))
        if vente:
            day['vente'] += 1
            day['ca'] += int(round(c.get('prix_confirme') or c.get('prix') or 0))
        if (c.get('vente') or '').upper() == 'FOLLOW_UP': day['followup'] += 1
    ads = {'old': collections.defaultdict(lambda: collections.Counter()), 'new': collections.defaultdict(lambda: collections.Counter())}
    ignored = collections.Counter()
    for o in json.load(open(os.path.join(SRC, 'ads_daily_raw.json'))):
        if NEW_CAMPAIGN_RE.search(o['camp']): f = 'new'
        elif WEBI_CAMPAIGN_RE.search(o['camp']):
            ignored[o['camp']] += 1; continue
        else: f = 'old'
        day = ads[f][o['d']]
        day['spend'] += o['spend']; day['clicks'] += o['clicks']; day['link'] += int(o['link']); day['lpv'] += int(o['lpv']); day['vv'] += int(o['vv'])
    res = {'fetched_at': dt.datetime.now().strftime('%d/%m/%Y %H:%M'), 'since': SINCE,
           'closing': {f: {k: dict(v) for k, v in sorted(closing[f].items())} for f in closing},
           'ads': {f: {k: {kk: (round(vv, 2) if kk == 'spend' else vv) for kk, vv in v.items()} for k, v in sorted(ads[f].items())} for f in ads}}
    json.dump(res, open(os.path.join(SRC, 'daily_sources.json'), 'w'), ensure_ascii=False)
    tot = lambda f, k: sum(v.get(k, 0) for v in closing[f].values())
    print('closing old : booked', tot('old', 'booked'), 'present', tot('old', 'present'), 'ventes', tot('old', 'vente'), 'CA', tot('old', 'ca'), '| new : booked', tot('new', 'booked'), 'resa', tot('new', 'resa'), '| webi ignores', n_webi, '| doublons inter-onglets ignores', n_dup)
    ta = lambda f, k: sum(v.get(k, 0) for v in ads[f].values())
    print('ads VSL old : link', ta('old', 'link'), 'lpv', ta('old', 'lpv'), 'spend', round(ta('old', 'spend')), '| new : lpv', ta('new', 'lpv'), '| campagnes ignorees (webinaire etc.) :', len(ignored))

if __name__ == '__main__':
    if '--no-closing' not in sys.argv: fetch_closing()
    if '--no-ads' not in sys.argv: fetch_ads()
    aggregate()
