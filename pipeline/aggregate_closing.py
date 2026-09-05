#!/usr/bin/env python3
"""Prépare closing-data.json pour la console closing (calls 2026 enrichis).

Usage: python3 aggregate_closing.py data.json closing-data.json "10/08/2026 22:00"
"""
import datetime as dt
import json
import re
import sys

RELANCE_KWS = r"(relance|relanc|rappel|rappeler|recontact|revenir|reviens|retour|follow[- ]?up|redonner|redonnera|news|nouvelles|sms|r2|rdv|prevu|prévu|planifi|inscription|point)"
PASSE_KWS = r"(depuis|il y a|ya|y a|ca fait|ça fait)\s*$"
MOIS_FR = {"janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5,
           "juin": 6, "juillet": 7, "aout": 8, "août": 8, "septembre": 9,
           "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12}
JOURS_FR = {"lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4,
            "samedi": 5, "dimanche": 6}


def relance_estimee(com, call_date):
    """Estime la date de relance depuis le commentaire closing (texte libre).

    Formats couverts : dates jj/mm près d'un mot-clé de relance, « 4 mai »,
    « début juin », jours de la semaine, « demain », « dans X jours »,
    « semaine pro », « quinzaine ». Les mentions tournées vers le passé
    (« depuis 2 mois », « il y a 3 jours ») sont écartées.
    """
    if not com or not call_date:
        return None
    try:
        base = dt.date.fromisoformat(call_date)
    except ValueError:
        return None
    low = com.lower()
    cands = []

    def past_ref(start):
        return re.search(PASSE_KWS, low[max(0, start - 14):start])

    def keep(cand):
        if base <= cand <= base + dt.timedelta(days=120):
            cands.append(cand)

    # jj/mm(/aa) près d'un mot-clé de relance
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", low):
        d, mo = int(m.group(1)), int(m.group(2))
        if not (1 <= d <= 31 and 1 <= mo <= 12) or past_ref(m.start()):
            continue
        y = int(m.group(3)) if m.group(3) else base.year
        if y < 100:
            y += 2000
        try:
            cand = dt.date(y, mo, d)
        except ValueError:
            continue
        if not m.group(3) and cand < base:
            cand = dt.date(y + 1, mo, d)
        if re.search(RELANCE_KWS, low[max(0, m.start() - 80):m.end() + 80]):
            keep(cand)

    # « 4 mai », « 1er juin »
    for m in re.finditer(r"\b(\d{1,2})(?:er)?\s+(" + "|".join(MOIS_FR) + r")\b", low):
        if past_ref(m.start()):
            continue
        d, mo = int(m.group(1)), MOIS_FR[m.group(2)]
        if not 1 <= d <= 31:
            continue
        y = base.year
        try:
            cand = dt.date(y, mo, d)
        except ValueError:
            continue
        if cand < base:
            cand = dt.date(y + 1, mo, d)
        keep(cand)

    # « début juin », « mi-juin », « fin juin »
    for m in re.finditer(r"\b(debut|début|mi|fin)[\s-]+(" + "|".join(MOIS_FR) + r")\b", low):
        if past_ref(m.start()):
            continue
        day = {"debut": 3, "début": 3, "mi": 15, "fin": 25}[m.group(1)]
        mo = MOIS_FR[m.group(2)]
        cand = dt.date(base.year, mo, day)
        if cand < base:
            cand = dt.date(base.year + 1, mo, day)
        keep(cand)

    # jours de la semaine (prochaine occurrence après le call)
    for m in re.finditer(r"\b(" + "|".join(JOURS_FR) + r")\b", low):
        if past_ref(m.start()):
            continue
        # évite le doublon avec « lundi 4 mai » (déjà couvert au-dessus)
        after = low[m.end():m.end() + 14]
        if re.match(r"\s+\d", after):
            continue
        delta = (JOURS_FR[m.group(1)] - base.weekday() - 1) % 7 + 1
        keep(base + dt.timedelta(days=delta))

    # expressions relatives
    m = re.search(r"\bdans\s+(\d{1,2})\s+jours?\b", low)
    if m and not past_ref(m.start()):
        keep(base + dt.timedelta(days=int(m.group(1))))
    for pat, days in [(r"apres[- ]demain|après[- ]demain", 2), (r"\bdemain\b", 1),
                      (r"semaine\s+pro(chaine)?\b", 7), (r"dans la semaine", 5),
                      (r"quinzaine", 15), (r"dans quelques jours", 4),
                      (r"dans un mois|mois prochain", 30), (r"la rentree|la rentrée", None)]:
        m = re.search(pat, low)
        if m and not past_ref(m.start()):
            if days is None:  # la rentrée = 1er septembre
                cand = dt.date(base.year, 9, 1)
                if cand < base:
                    cand = dt.date(base.year + 1, 9, 1)
                keep(cand)
            else:
                keep(base + dt.timedelta(days=days))

    return min(cands).isoformat() if cands else None


def _norm_name(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    toks = sorted(t for t in re.split(r"[^a-z0-9]+", s) if len(t) > 1)
    return " ".join(toks)


def _call_day(iso_or_txt):
    """Date (YYYY-MM-DD, heure de Paris) du call transmise par la page merci."""
    s = (iso_or_txt or "").strip()
    m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})", s)
    if m:
        try:
            from zoneinfo import ZoneInfo
            t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
            if t.tzinfo:
                t = t.astimezone(ZoneInfo("Europe/Paris"))
            return t.date().isoformat()
        except Exception:
            return m.group(1)
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else ""


def attach_wa_confirms(calls, confirms):
    """Pose sur chaque call : wac (1er clic WhatsApp, 'YYYY-MM-DD HH:MM'),
    wan (nb de clics), war (date où le closer a coché « reçu », '' sinon).
    Retourne les confirmations qu'on n'a pu rattacher à aucune ligne du Sheet."""
    by_mail, by_name = {}, {}
    for c in calls:
        if c["mail"]:
            by_mail.setdefault(c["mail"].lower().strip(), []).append(c)
        nn = _norm_name(c["n"])
        if nn:
            by_name.setdefault(nn, []).append(c)

    def pick(cands, day):
        if not cands:
            return None
        if day:
            same = [c for c in cands if c["d"] == day]
            if same:
                return same[-1]
            fut = [c for c in cands if c["d"] and c["d"] >= day]
            if fut:
                return min(fut, key=lambda c: c["d"])
        return max(cands, key=lambda c: c["d"] or "")

    orphans = {}
    for cf in sorted(confirms, key=lambda x: x["d"]):
        day = _call_day(cf["call"])
        cands = by_mail.get(cf["email"]) if cf["email"] else None
        if not cands:
            cands = by_name.get(_norm_name(cf["lead"]))
        call = pick(cands, day)
        st = cf["statut"]
        if call is None:
            k = cf["email"] or _norm_name(cf["lead"])
            o = orphans.setdefault(k, {"lead": cf["lead"], "email": cf["email"], "closer": cf["closer"],
                                       "call": day, "wac": "", "wan": 0, "war": ""})
            if st == "CLIC":
                o["wan"] += 1
                o["wac"] = o["wac"] or cf["d"]
            elif st == "RECU":
                o["war"] = cf["d"][:10]
            elif st == "NONRECU":
                o["war"] = ""
            continue
        if st == "CLIC":
            call["wan"] = call.get("wan", 0) + 1
            call["wac"] = call.get("wac") or cf["d"]
        elif st == "RECU":
            call["war"] = cf["d"][:10]
        elif st == "NONRECU":
            call["war"] = ""
    return [o for o in orphans.values() if o["wac"] or o["war"]]


NEW_CAL_RE = re.compile(r"appel diagnostic\s*-\s*club", re.I)
OLD_CAL_RE = re.compile(r"investisseurs 3\.0|programme investisseu", re.I)
ADS_UTM_RE = re.compile(r"^(broad|utm_|ads|\[market|retargeting|funnel)", re.I)


def funnel_of(c):
    src = c.get("source") or ""
    src2 = (c.get("source2") or "").lower()
    utm = (c.get("utm") or "").strip()
    if c.get("webi"):
        return "webi"
    if NEW_CAL_RE.search(src):
        return "new"
    if "setting" in src2:
        return "org"
    if OLD_CAL_RE.search(src) or src2.startswith("vsl") or ADS_UTM_RE.match(utm):
        return "old"
    return "org"


# ── Leads Valar : rattachement aux calls I3 ──────────────────────────────────
VALAR_CLOSERS = [("louis", "Louis Granier"), ("romain", "Romain Gourand"), ("adrien", "Adrien Soret")]
VALAR_I3_RE = re.compile(r"i3|i\s*3\.0|club|closer|closing", re.I)
VALAR_NON_I3_RE = re.compile(r"non\s*i3|pas\s*i3|hors\s*i3", re.I)


def _valar_name_key(n):
    import unicodedata
    n = unicodedata.normalize("NFD", n or "")
    n = "".join(ch for ch in n if unicodedata.category(ch) != "Mn").lower()
    toks = [t for t in re.split(r"[^a-z]+", n) if len(t) > 1]
    return " ".join(sorted(toks))


def _valar_by_surname(nom, calls):
    """Secours : « Denis Cordier » chez Valar, « D Cordier » dans le Sheet closing.
    Le nom de famille (token le plus long, 5 lettres et plus) doit désigner un
    seul prospect, dont les autres tokens commencent par les mêmes lettres."""
    toks = _valar_name_key(nom).split()
    longs = sorted((t for t in toks if len(t) >= 5), key=len, reverse=True)
    if not longs:
        return None
    sur = longs[0]
    others = [t[0] for t in toks if t != sur]
    found = {}
    for c in calls:
        ct = _valar_name_key(c.get("n")).split()
        if sur not in ct:
            continue
        rest = [t for t in ct if t != sur]
        raw_first = [w[0].lower() for w in re.split(r"\s+", (c.get("n") or "").strip()) if w and w.lower() != sur]
        initials = set(t[0] for t in rest) | set(raw_first)
        if others and not all(o in initials for o in others):
            continue
        found[_valar_name_key(c.get("n")) or c.get("n")] = c
    return list(found.values())[0] if len(found) == 1 else None


def attach_valar(calls, valar, claims=()):
    """Chaque lead Valar est rattaché au call I3 correspondant (e-mail, sinon
    téléphone, sinon nom) : on en tire le closer, la date et l'issue du call.
    Le closer nommé dans la colonne Source de Valar prime quand il y est.
    « i3 » = lead envoyé par un closer I3 (source ou call retrouvé)."""
    by_mail, by_tel, by_name = {}, {}, {}
    for c in sorted(calls, key=lambda c: c.get("d") or ""):
        m = (c.get("mail") or "").strip().lower()
        t = re.sub(r"\D", "", c.get("tel") or "")
        k = _valar_name_key(c.get("n"))
        if m:
            by_mail[m] = c
        if len(t) >= 9:
            by_tel[t[-9:]] = c
        if k:
            by_name[k] = c
    for l in valar.get("leads", []):
        c = None
        if l.get("mail"):
            c = by_mail.get(l["mail"])
        if c is None and len(l.get("tel") or "") >= 9:
            c = by_tel.get(l["tel"][-9:])
        if c is None:
            c = by_name.get(_valar_name_key(l.get("n")))
        if c is None:
            c = _valar_by_surname(l.get("n"), calls)
        src = l.get("src") or ""
        from_src = [full for key, full in VALAR_CLOSERS if re.search(key, src, re.I)]
        l["cl"] = from_src[0] if from_src else (c["c"] if c else "")
        l["cl2"] = from_src[1] if len(from_src) > 1 else ""
        l["how"] = "src" if from_src else ("call" if c else "")
        if c:
            l["cd"] = c.get("d")        # date du call I3
            l["cv"] = c.get("v")        # issue du call I3 (OUI / FOLLOW_UP / NON…)
            l["cs"] = c.get("s")        # show-up du call I3
            l["cn"] = c.get("n")        # nom tel qu'écrit dans le Sheet closing
        i3_src = bool(VALAR_I3_RE.search(src)) and not VALAR_NON_I3_RE.search(src)
        l["i3"] = bool(from_src or i3_src or c)
    # doublons du Sheet (même nom dans le même onglet) : on garde la ligne la
    # plus renseignée (source, mail, commentaire), la seconde disparaît
    seen = {}
    for l in valar.get("leads", []):
        k = (l["stage"], _valar_name_key(l["n"]))
        score = sum(1 for f in ("src", "mail", "tel", "com", "r1", "r2") if l.get(f))
        if k not in seen or score > seen[k][0]:
            seen[k] = (score, l)
    valar["leads"] = [x[1] for x in seen.values()]
    # Réclamations (onglet Sheet « Reclamations Valar ») : la dernière décision par lead
    # Valar fait foi. VALIDE = le lead passe sous le closer réclamant ; EN_ATTENTE = signalé
    # sur le lead en attendant Alex ; REFUSE = rien ne change. Toutes remontent à la console
    # (bloc « Réclamations » en haut de l'onglet + validation dans l'onglet Alex).
    claims = list(claims)
    last = {}
    for cl in claims:
        key = cl.get("lead_id") or _valar_name_key(cl.get("lead"))
        last[key] = cl
    for l in valar["leads"]:
        cl = last.get(l["id"]) or last.get(_valar_name_key(l["n"]))
        if not cl:
            continue
        if cl["statut"] == "VALIDE" and cl.get("closer"):
            l["cl"], l["cl2"], l["how"], l["i3"] = cl["closer"], "", "claim", True
        elif cl["statut"] == "EN_ATTENTE":
            l["pend"] = cl.get("closer") or ""
    valar["claims"] = [{"d": c["d"], "id": c["id"], "lid": c.get("lead_id") or "", "n": c["lead"],
                        "c": c["closer"], "stage": c.get("stage") or "", "st": c["statut"],
                        "dd": c.get("dd") or "", "com": c.get("com") or ""} for c in claims]
    return valar


def main(data_path, out_path, updated_at):
    d = json.load(open(data_path))
    calls = []
    for c in d["calls"]:
        # tous les onglets closing parsés (déc. 2025 inclus)
        prix_eff = c.get("prix_confirme") or c.get("prix") or 0
        calls.append({
            "d": c.get("date"),
            "hh": c.get("hour") or "",      # heure du call (HH:MM) si connue
            "b": c.get("booking_date"),
            "tm": f"{c['year']:04d}-{c['month']:02d}",
            "c": re.sub(r"\s+", " ", c.get("closer") or "").strip(),
            "n": (c.get("prospect") or "").strip(),
            "tel": c.get("phone") or "",
            "mail": c.get("mail") or "",
            "s": c.get("show_up") or "",
            "al": bool(c.get("annule_lead")),   # annulé par le lead (bouton console)
            "v": c.get("vente") or "",
            "q": c.get("qualif"),
            "pp": round(c.get("prix") or 0),          # prix proposé
            # vente comptée si validée par le closer (OUI) OU par Justine (virement)
            "p": round(prix_eff) if (c.get("vente") in ("OUI", "REMBOURSEMENT") or c.get("virement")) else 0,
            "vir": bool(c.get("virement")),
            "com": (c.get("commentaire") or "").strip(),
            "obj": (c.get("objection") or "").strip(),
            "mens": (c.get("mensualites") or "").strip(),
            # case à cocher dans le Sheet : TRUE/FALSE -> OUI/NON
            "c250": {"TRUE": "OUI", "OUI": "OUI", "VRAI": "OUI",
                     "FALSE": "NON", "NON": "NON", "FAUX": "NON"}.get(
                         (c.get("cash250") or "").strip().upper(), ""),
            # texte libre : Oui / Non / Pas regardé
            "vid": ("OUI" if (c.get("video") or "").strip().upper().startswith("OUI")
                    else "NON" if (c.get("video") or "").strip().upper().startswith("NON")
                    else "PAS" if (c.get("video") or "").strip().upper().startswith("PAS")
                    else ""),
            "rec": (c.get("recording") or "").strip(),
            "rel": c.get("relance"),
            "r2": c.get("r2"),
            # date où la vente a été cochée (registre sales_ledger), sinon absent
            "sd": c.get("sale_date"),
            "relEst": relance_estimee(c.get("commentaire"), c.get("date")),
            "hasS": bool(c.get("has_show_up_raw")),
            "hasV": bool(c.get("has_vente_raw")),
            "st": c.get("tab"),          # onglet + ligne Sheet : écriture retour
            "sr": c.get("row"),
            "rf": (c.get("relance_faite") or "").strip(),
            "utm": (c.get("utm") or "").strip()[:40],
            # canal du call : webi (onglets webinaire), new (calendrier iClosed « Appel Diagnostic - Club »,
            # nouvelle LP VSL), old (VSL / Calendly Investisseurs 3.0 / ads), org (setting, site, sans attribution)
            "fun": funnel_of(c),
        })

    eod_appel = [r for r in d.get("setter_reports", []) if r.get("year") == 2026]
    eod_ecrit = [r for r in d.get("dm_reports", []) if r.get("year") == 2026]
    eod_setter = [r for r in d.get("setter_console", []) if r.get("year") == 2026]
    history = sorted(d.get("history", []), key=lambda h: h["ts"], reverse=True)[:500]
    csm = [{
        "row": x["row"], "c": x["closer"], "n": x["name"], "mail": x["mail"], "tel": x["phone"], "r1": x["r1"],
        "q": x["qualif"], "v": x["vente"], "vir": x["virement"], "r2": x["r2"], "com": x["comment"],
        "dv": x["date_vente"], "csm": x["csm"], "valar": x["valar"], "j0": x["j0"], "j10d": x["j10_date"], "j10": x["j10"],
        "k": x["calls"], "nf": x["new_offer"], "tem": x["temoignage"], "reco": x["reco"], "slots": x["slots"], "last": x["last_slot"],
    } for x in d.get("csm", [])]
    # semaines ads (spend + résas) pour le brief : chargées depuis ads.json si présent
    weeks = []
    try:
        import os
        ads_path = os.path.join(os.path.dirname(os.path.abspath(out_path)) or ".", "ads.json")
        ads = json.load(open(ads_path))
        weeks = [{"start": w["start"], "spend": w["spend"], "booked": w["calls_booked"]}
                 for w in ads.get("weeks", [])]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    hrows = {c["tab"]: c["hrow"] for c in d["calls"] if c.get("tab") and c.get("hrow")}

    # leads iClosed (formulaire rempli, pas de réservation) + état de relance :
    # dernière ligne de « Relances iClosed » par lead = état courant
    iclosed = d.get("iclosed", [])
    last_claim = {}
    for cl in d.get("iclosed_claims", []):
        last_claim[cl["lead"]] = cl
    for l in iclosed:
        cl = last_claim.get(l["e"])
        if cl and cl.get("statut") != "ANNULE":
            l["cl"] = cl.get("closer") or ""
            l["cld"] = cl.get("d") or ""

    # confirmations WhatsApp (page merci : clic ; console : reçu / non reçu),
    # rattachées aux calls par e-mail, sinon par nom ; le reste = orphelines
    wa_orphans = attach_wa_confirms(calls, d.get("wa_confirms", []))

    # Tally « Le Scan Patrimoine » : tally.json écrit par tally_fetch.py.
    # Relances partagées : mêmes lignes « Relances iClosed » que l'onglet À
    # relancer, avec un lead préfixé TALLY| (email, sinon id de soumission).
    tally = {}
    try:
        import os
        tally_path = os.path.join(os.path.dirname(os.path.abspath(out_path)) or ".", "tally.json")
        tally = json.load(open(tally_path))
        ty_claim = {}
        for cl in d.get("iclosed_claims", []):
            if (cl.get("lead") or "").startswith("TALLY|"):
                ty_claim[cl["lead"][6:]] = cl
        for s in tally.get("subs", []):
            cl = ty_claim.get(s.get("email") or s["id"])
            if not cl or cl.get("statut") == "ANNULE":
                continue
            # scan de test coché dans la console : sorti de toutes les stats
            if cl.get("statut") == "TEST":
                s["test"] = True
            else:
                s["cl"] = cl.get("closer") or ""
                s["cld"] = cl.get("d") or ""
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Leads Valar : valar.json écrit par valar_fetch.py (CRM business Valar).
    # Les closers I3 y suivent l'avancée des prospects envoyés en appel.
    valar = {}
    try:
        import os
        valar_path = os.path.join(os.path.dirname(os.path.abspath(out_path)) or ".", "valar.json")
        valar = attach_valar(calls, json.load(open(valar_path)), d.get("valar_claims", []))
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    out = {"updated_at": updated_at, "calls": calls, "hrows": hrows,
           "iclosed": iclosed, "wa_orphans": wa_orphans, "tally": tally, "valar": valar,
           "eod_appel": eod_appel, "eod_ecrit": eod_ecrit, "eod_setter": eod_setter, "history": history, "csm": csm, "weeks": weeks}
    with open(out_path, "w") as f:
        json.dump(out, f, ensure_ascii=False)

    fu = [c for c in calls if c["v"] == "FOLLOW_UP"]
    nv = [c for c in calls if c["v"] == "OUI" and not c["vir"]]
    print(f"calls={len(calls)} follow-ups={len(fu)} ventes sans virement={len(nv)}",
          file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
