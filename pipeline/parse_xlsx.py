#!/usr/bin/env python3
"""Parse le classeur xlsx 'INVESTISSEURS 3.0' complet en data.json.

Usage: python3 parse_xlsx.py investisseurs30.xlsx data.json
"""
import datetime as dt
import json
import re
import sys
import unicodedata
from collections import Counter

import openpyxl

# onglet -> (année, mois, webi ?)
CLOSING_TABS = {
    "Suivi Closing Aout": (2026, 8, False),
    "Suivi Closing JUILLET": (2026, 7, False),
    "Suivi Closing JUIN": (2026, 6, False),
    "Suivi Closing MAI": (2026, 5, False),
    "WEBI AVRIL SUIVI CLOSING": (2026, 4, True),
    "Suivi Closing AVRIL": (2026, 4, False),
    "Suivi Closing MARS": (2026, 3, False),
    "Suivi Closing FEVRIER": (2026, 2, False),
    "SUIVI CLOSING WEBI JANVIER": (2026, 1, True),
    "SUIVI CLOSING DECEMBRE 2025": (2025, 12, False),
}
SETTING_TABS = {"Lead Setting Avril": (2026, 4), "Lead setting Mars": (2026, 3),
                "Lead setting Fevrier": (2026, 2)}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def cell_str(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%d/%m/%Y")
    return str(v).strip()


def parse_time(v):
    """Heure du call (HH:MM) si la cellule la contient, sinon ''."""
    if isinstance(v, dt.datetime):
        return f"{v.hour:02d}:{v.minute:02d}" if (v.hour or v.minute) else ""
    s = cell_str(v)
    m = re.search(r"(\d{1,2})\s*[:hH]\s*(\d{2})", s or "")
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return ""


def parse_date(v):
    if isinstance(v, (dt.datetime, dt.date)):
        return (v.year, v.month, v.day)
    s = cell_str(v)
    if not s:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 2024 <= y <= 2027 and 1 <= mo <= 12:
            return (y, mo, d)
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 2024 <= y <= 2027 and 1 <= mo <= 12 and 1 <= d <= 31:
            return (y, mo, d)
    return None


def parse_num(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("€", "").replace("\xa0", "").replace(" ", "").strip()
    s = s.replace(",", ".")
    return float(s) if re.match(r"^-?\d+(\.\d+)?$", s) else None


COL_MAP = {
    "closer": "closer", "colonne 1": "closer",
    "date de l'appel": "date", "date de l'appel r1": "date",
    "nom prenom prospect": "prospect", "prenom nom lead": "prospect",
    "show up r1 ?": "show_up", "show up": "show_up",
    "qualifie /10": "qualif",
    "vente ?": "vente", "vente r1 ?": "vente",
    "prix propose": "prix", "prix": "prix",
    "prix confirme par justine": "prix_confirme",
    "mensutalites": "mensualites", "mensualites": "mensualites",
    "source du call": "source", "source du call 2": "source2",
    "d'ou vient le lead": "lead_source",
    "utm quel ads": "utm",
    "date booking call": "booking_date",
    "virement recu valide par justine": "virement",
    "telephone": "phone",
    "mail": "mail",
    "commentaires closing": "commentaire",
    "prospect 250k": "cash250",           # « Prospect +250k cash à placer » (le + saute au norm)
    "prospect a vu video": "video",       # « Prospect à vu vidéo préchauffe ? »
    "enregistrement appel": "recording",
    "objection/peur principale": "objection",
    "date de relance a faire": "relance",
    "date r2": "r2",
    "relance faite": "relance_faite",  # colonne ajoutée par la console (coche Relancé)
}


def map_header(cells):
    mapping = {}
    keys_by_len = sorted(COL_MAP.items(), key=lambda kv: -len(kv[0]))
    for idx, c in enumerate(cells):
        n = norm(cell_str(c))
        n = re.sub(r"[^a-z0-9/'? .-]", "", n).strip()
        if not n:
            continue
        for key, field in keys_by_len:
            if n == key or n.startswith(key):
                if field not in mapping:
                    mapping[field] = idx
                break
    return mapping


def norm_show_up(s):
    n = norm(s or "")
    if n.startswith("oui"):
        return "OUI"
    if n.startswith("reprog"):
        return "REPROGRAMMER"
    if n.startswith("non") or n.startswith("no show"):
        return "NON"
    if n.startswith("annul") or n.startswith("supprim"):
        return "ANNULE"
    if n.startswith("doubl"):
        return "DOUBLON"
    return "" if not n else "AUTRE"


def norm_vente(s):
    n = norm(s or "")
    if not n:
        return ""
    if "rembours" in n:
        return "REMBOURSEMENT"
    if "non pitch" in n or ("pitche" in n and n.startswith("non")):
        return "NON_PITCHE"
    if n.startswith("oui"):
        return "OUI"
    if "follow" in n or "en cours" in n:
        return "FOLLOW_UP"
    if n.startswith("non"):
        return "NON"
    return "AUTRE"


def find_header(rows_iter, must_have, scan=12):
    """Retourne (header_row_idx, header_cells) sur les `scan` premières lignes."""
    buf = []
    for i, row in enumerate(rows_iter):
        buf.append(row)
        if i >= scan:
            break
    for i, row in enumerate(buf):
        joined = norm(" ".join(cell_str(c) for c in row))
        if all(k in joined for k in must_have):
            return i, row
    return None, None


def main(xlsx_path, out_path):
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    calls, stripe, settings_rows, setter_reports, dm_reports = [], [], [], [], []
    setter_console = []  # onglet « EOD Setter Console » (EOD de Constant saisi dans la console)
    history = []  # onglet « Historique Console » (modifs faites depuis la console, pont v14)
    csm = []  # onglet « CSM » : suivi post-vente (3 calls d'accompagnement, mails V1, témoignages)
    iclosed_leads, iclosed_claims, wa_confirms, valar_claims = [], [], [], []

    for ws in wb.worksheets:
        title = ws.title.strip()
        all_rows = list(ws.iter_rows(values_only=True))

        if ws.title in CLOSING_TABS or title in CLOSING_TABS:
            year, month, webi = CLOSING_TABS.get(ws.title) or CLOSING_TABS[title]
            hidx, header = find_header(iter(all_rows), ["show up", "vente"])
            if header is None:
                continue
            mapping = map_header(header)
            # ridx = numéro de ligne réel dans le Sheet (1-based), pour l'écriture retour
            for ridx, r in enumerate(all_rows[hidx + 1:], start=hidx + 2):
                def g(f):
                    i = mapping.get(f)
                    return r[i] if i is not None and i < len(r) else None
                closer = cell_str(g("closer"))
                prospect = cell_str(g("prospect"))
                d = parse_date(g("date"))
                if not closer and not prospect:
                    continue
                # garde-fou anti-blocs parasites à droite des tabs
                if closer and len(closer) > 60:
                    continue
                # lignes de test (résas « alex test » faites pour tester le funnel)
                if re.search(r"\btests?\b", prospect, re.I):
                    continue
                show_up_raw = cell_str(g("show_up"))
                show_up = norm_show_up(show_up_raw)
                # « Annulé par le lead » / « Supprimé » (bouton console) : reste ANNULE
                # pour les stats, avec un drapeau pour la base des leads annulés
                annule_lead = show_up == "ANNULE" and ("lead" in norm(show_up_raw) or norm(show_up_raw).startswith("supprim"))
                # ligne marquée DOUBLON (coche console ou saisie manuelle) : ignorée
                # partout (consoles, stats, briefs, mails), le Sheet garde la trace
                if show_up == "DOUBLON":
                    continue
                vente = norm_vente(cell_str(g("vente")))
                # règle Alex 28/08 : un résultat rempli (vente, follow-up, non pitché...)
                # implique que le lead était présent, même si SHOW UP est resté vide
                if not show_up and vente in ("OUI", "NON", "FOLLOW_UP", "NON_PITCHE", "REMBOURSEMENT"):
                    show_up = "OUI"
                booking = parse_date(g("booking_date"))
                relance = parse_date(g("relance"))
                r2 = parse_date(g("r2"))
                calls.append({
                    "tab": title, "webi": webi, "row": ridx, "hrow": hidx + 1,
                    "closer": re.sub(r"\s+", " ", closer),
                    "prospect": prospect,
                    "date": f"{d[0]:04d}-{d[1]:02d}-{d[2]:02d}" if d else None,
                    "hour": parse_time(g("date")),
                    "year": year, "month": month,
                    "show_up": show_up, "vente": vente, "annule_lead": annule_lead,
                    "qualif": parse_num(g("qualif")),
                    "prix": parse_num(g("prix")),
                    "prix_confirme": parse_num(g("prix_confirme")),
                    "virement": cell_str(g("virement")) == "TRUE",
                    "source": cell_str(g("source")), "source2": cell_str(g("source2")),
                    "utm": cell_str(g("utm")), "lead_source": cell_str(g("lead_source")),
                    "booking_date": f"{booking[0]:04d}-{booking[1]:02d}-{booking[2]:02d}" if booking else None,
                    "phone": cell_str(g("phone"))[:20],
                    "mail": cell_str(g("mail"))[:80],
                    "commentaire": cell_str(g("commentaire"))[:600],
                    "objection": cell_str(g("objection"))[:300],
                    "mensualites": cell_str(g("mensualites"))[:40],
                    "cash250": cell_str(g("cash250"))[:20],
                    "video": cell_str(g("video"))[:20],
                    "recording": cell_str(g("recording"))[:200],
                    "relance": f"{relance[0]:04d}-{relance[1]:02d}-{relance[2]:02d}" if relance else None,
                    "r2": f"{r2[0]:04d}-{r2[1]:02d}-{r2[2]:02d}" if r2 else None,
                    "relance_faite": cell_str(g("relance_faite"))[:30],
                    "has_show_up_raw": bool(cell_str(g("show_up"))),
                    "has_vente_raw": bool(cell_str(g("vente"))),
                    "has_qualif_raw": bool(cell_str(g("qualif"))),
                })
            continue

        if title == "iClosed Import":
            # rempli par iclosed_import.py via le pont : Email, Prénom, Nom, Tél,
            # Créé le, UTM source, UTM campagne, UTM contenu
            for r in all_rows[1:]:
                if not r or not cell_str(r[0] if len(r) > 0 else None):
                    continue
                def g(i):
                    return cell_str(r[i]) if i < len(r) else ""
                iclosed_leads.append({"e": g(0), "pn": g(1), "n": g(2), "tel": g(3),
                                      "d": g(4)[:16], "src": g(5), "camp": g(6), "ad": g(7)})
            continue

        if title == "Relances iClosed":
            # rempli par la console via le pont : Date, Lead(email), Closer, Statut
            for r in all_rows[1:]:
                if not r or not cell_str(r[1] if len(r) > 1 else None):
                    continue
                iclosed_claims.append({"d": cell_str(r[0])[:16],
                                       "lead": cell_str(r[1]),
                                       "closer": cell_str(r[2]) if len(r) > 2 else "",
                                       "statut": cell_str(r[3]) if len(r) > 3 else ""})
            continue

        if title == "Reclamations Valar":
            # rempli par la console (onglet Leads Valar, bouton « Réclamer un lead ») via le pont v16 :
            # Date, Id, Lead Valar (_ID), Lead, Closer, Etape, Statut (EN_ATTENTE / VALIDE / REFUSE),
            # Decide le, Commentaire. Alex décide depuis l'onglet Alex. Closers « Test* » ignorés.
            for r in all_rows[1:]:
                if not r or not cell_str(r[1] if len(r) > 1 else None):
                    continue
                def g(i):
                    return cell_str(r[i]) if i < len(r) else ""
                if g(4).startswith("Test"):
                    continue
                valar_claims.append({"d": g(0)[:16], "id": g(1), "lead_id": g(2), "lead": g(3),
                                     "closer": g(4), "stage": g(5), "statut": g(6) or "EN_ATTENTE",
                                     "dd": g(7)[:16], "com": g(8)[:300]})
            continue

        if title == "Confirmations WhatsApp":
            # rempli par le pont : clic sur le bouton WhatsApp de la page merci
            # (statut CLIC, source page) ou coche du closer dans la console
            # (RECU / NONRECU, source console). Colonnes : Date, Lead, Email,
            # Closer, Call, Statut, Source, UTM. Les lignes source=test sont ignorées.
            for r in all_rows[1:]:
                if not r or len(r) < 6:
                    continue
                def g(i):
                    return cell_str(r[i]) if i < len(r) else ""
                src = g(6).lower()
                if src == "test" or g(2).lower().endswith("@example.com") or (not g(1) and not g(2)):
                    continue
                dv = r[0]
                when = dv.strftime("%Y-%m-%d %H:%M") if isinstance(dv, dt.datetime) else g(0)[:16]
                wa_confirms.append({"d": when, "lead": g(1)[:80], "email": g(2).lower()[:80],
                                    "closer": g(3)[:40], "call": g(4)[:40],
                                    "statut": g(5).upper()[:12], "source": src[:12], "utm": g(7)[:100]})
            continue

        if title == "Ventes":
            hidx, header = find_header(iter(all_rows), ["vente_id"])
            if header is None:
                continue
            hmap = {norm(cell_str(c)): i for i, c in enumerate(header)}
            for r in all_rows[hidx + 1:]:
                def g(k):
                    i = hmap.get(k)
                    return r[i] if i is not None and i < len(r) else None
                d = parse_date(g("date"))
                amt = parse_num(g("montant_ttc"))
                if d and amt is not None:
                    stripe.append({"date": f"{d[0]:04d}-{d[1]:02d}-{d[2]:02d}",
                                   "year": d[0], "month": d[1],
                                   "nom": cell_str(g("nom")), "montant_ttc": amt})
            continue

        if ws.title in SETTING_TABS or title in SETTING_TABS:
            year, month = SETTING_TABS.get(ws.title) or SETTING_TABS[title]
            hidx, header = find_header(iter(all_rows), ["date optin"])
            if header is None:
                continue
            oi = bi = None
            for i, c in enumerate(header):
                n = norm(cell_str(c))
                if "date optin" in n:
                    oi = i
                elif n.startswith("call booke"):
                    bi = i
            for r in all_rows[hidx + 1:]:
                if oi is None or oi >= len(r) or not cell_str(r[oi]):
                    continue
                booked = bi is not None and bi < len(r) and norm(cell_str(r[bi])).startswith("oui")
                settings_rows.append({"year": year, "month": month, "booked": booked})
            continue

        if title == "EOD Setting Appel":
            hidx, header = find_header(iter(all_rows), ["nouveau lead appele"])
            if header is None:
                continue
            idx = {}
            for i, c in enumerate(header):
                n = norm(cell_str(c))
                if n.startswith("date du jour"):
                    idx["date"] = i
                elif "nom du setter" in n:
                    idx["setter"] = i
                elif "numero optin" in n:
                    idx["optins"] = i
                elif "nouveau lead appele" in n:
                    idx["appeles"] = i
                elif n.startswith("nombre de reponses au call (pour les nouveaux"):
                    idx["reponses"] = i
                elif "relance de lead rappele" in n:
                    idx["relances"] = i
                elif n.startswith("nombre de reponses au call (pour les relan"):
                    idx["rep_rel"] = i
                elif "appel de vente proposes" in n:
                    idx["proposes"] = i
                elif "appel acceptes" in n:
                    idx["acceptes"] = i
                elif "qu'elle est la raison" in n or "quelle est la raison" in n:
                    idx["raison"] = i
                elif "idees pour ameliorer" in n:
                    idx["idees"] = i
            for r in all_rows[hidx + 1:]:
                def g(k):
                    i = idx.get(k)
                    return r[i] if i is not None and i < len(r) else None
                d = parse_date(g("date"))
                if not d:
                    continue
                setter_reports.append({"year": d[0], "month": d[1],
                                       "d": f"{d[0]:04d}-{d[1]:02d}-{d[2]:02d}",
                                       "setter": cell_str(g("setter"))[:30],
                                       "optins": parse_num(g("optins")) or 0,
                                       "appeles": parse_num(g("appeles")) or 0,
                                       "reponses": parse_num(g("reponses")) or 0,
                                       "relances": parse_num(g("relances")) or 0,
                                       "rep_rel": parse_num(g("rep_rel")) or 0,
                                       "proposes": parse_num(g("proposes")) or 0,
                                       "acceptes": parse_num(g("acceptes")) or 0,
                                       "raison": cell_str(g("raison"))[:220],
                                       "idees": cell_str(g("idees"))[:220]})
            continue

        if title == "CSM":
            hidx, header = find_header(iter(all_rows), ["nom du csm"])
            if header is None:
                continue
            idx = {}
            for i, c in enumerate(header):
                n = norm(cell_str(c))
                for key, needle in (("closer", "closer"), ("r1", "date de l'appel"), ("name", "nom prenom"), ("mail", "mail"),
                                    ("phone", "telephone"), ("show_up", "show up"), ("qualif", "qualifie"), ("cash250", "prospect"),
                                    ("vente", "vente"), ("virement", "virement"), ("r2", "r2"), ("comment", "commentaires"),
                                    ("date_vente", "date vente"), ("csm", "nom du csm"), ("valar", "lead potentiel valar"),
                                    ("j0", "j-0"), ("j10_date", "j+10 date"), ("j10", "envoye a j+10"),
                                    ("c1d", "call 1 — date"), ("c1s", "call 1 — statut"), ("c2d", "call 2 — date"), ("c2s", "call 2 — statut"),
                                    ("c3d", "call 3 — date"), ("c3s", "call 3 — statut"), ("new_offer", "nouvelle offre"),
                                    ("temoignage", "temoignage"), ("reco", "reco"), ("slots", "slots 15"), ("last_slot", "dernier slot")):
                    if n.startswith(needle) and key not in idx:
                        idx[key] = i
                        break
            def iso_of(v):
                d = parse_date(v)
                return f"{d[0]:04d}-{d[1]:02d}-{d[2]:02d}" if d else None
            def truthy(v):
                return cell_str(v).strip().upper() in ("TRUE", "OUI", "VRAI", "YES", "X")
            for ridx, r in enumerate(all_rows[hidx + 1:], start=hidx + 2):
                def g(k):
                    i = idx.get(k)
                    return r[i] if i is not None and i < len(r) else None
                name = re.sub(r"\s+", " ", cell_str(g("name"))).strip()
                if not name or re.search(r"\btests?\b", name, re.I):
                    continue
                ph = g("phone")
                phone = str(int(ph)) if isinstance(ph, float) else re.sub(r"\D", "", cell_str(ph))
                csm.append({
                    "row": ridx, "closer": re.sub(r"\s+", " ", cell_str(g("closer"))).strip(), "r1": iso_of(g("r1")),
                    "name": name[:60], "mail": cell_str(g("mail"))[:80].strip(), "phone": phone[:20],
                    "show_up": norm_show_up(cell_str(g("show_up"))), "qualif": parse_num(g("qualif")),
                    "cash250": truthy(g("cash250")), "vente": norm_vente(cell_str(g("vente"))), "virement": truthy(g("virement")),
                    "r2": cell_str(g("r2"))[:30].strip(), "comment": cell_str(g("comment"))[:600],
                    "date_vente": iso_of(g("date_vente")), "csm": cell_str(g("csm")).strip()[:30],
                    "valar": truthy(g("valar")), "j0": truthy(g("j0")), "j10_date": iso_of(g("j10_date")), "j10": truthy(g("j10")),
                    "calls": [{"d": iso_of(g(f"c{n}d")), "st": cell_str(g(f"c{n}s")).strip()[:30]} for n in (1, 2, 3)],
                    "new_offer": truthy(g("new_offer")), "temoignage": truthy(g("temoignage")), "reco": truthy(g("reco")),
                    "slots": parse_num(g("slots")) or 0, "last_slot": iso_of(g("last_slot")),
                })
            continue

        if title == "Historique Console":
            # Date, Onglet, Ligne, Lead, Par, Action, Champs modifies (JSON)
            for r in all_rows[1:]:
                r = list(r) + [None] * 7
                ts = r[0]
                if not isinstance(ts, dt.datetime):
                    continue
                by = cell_str(r[4])
                if by.lower().startswith("test"):
                    continue
                history.append({"ts": ts.strftime("%Y-%m-%d %H:%M"), "tab": cell_str(r[1])[:40],
                                "row": parse_num(r[2]), "lead": cell_str(r[3])[:60], "by": by[:30],
                                "action": cell_str(r[5])[:60], "fields": cell_str(r[6])[:1500]})
            continue

        if title == "EOD Setter Console":
            # EOD du setter (Constant) saisi dans l'onglet « EOD Constant » de la console (pont v12)
            hidx, header = find_header(iter(all_rows), ["accroches envoyees"])
            if header is None:
                continue
            idx = {}
            for i, c in enumerate(header):
                n = norm(cell_str(c))
                for key, needle in (("ts", "date"), ("jour", "jour"), ("setter", "setter"), ("energie", "energie"),
                                    ("accroches", "accroches"), ("relances", "relances"), ("reponses", "reponses"),
                                    ("quali", "conversations"), ("proposes", "rdv proposes"), ("bookes", "rdv bookes"),
                                    ("objections", "objections"), ("retours", "retours"),
                                    ("audits", "audits"), ("contactes", "leads audit")):
                    if n.startswith(needle) and key not in idx:
                        idx[key] = i
                        break
            for r in all_rows[hidx + 1:]:
                def g(k):
                    i = idx.get(k)
                    return r[i] if i is not None and i < len(r) else None
                setter = cell_str(g("setter"))[:30]
                if not setter or setter.lower().startswith("test"):
                    continue
                d = parse_date(g("jour")) or parse_date(g("ts"))
                if not d:
                    continue
                ts = g("ts")
                heure = f"{ts.hour:02d}:{ts.minute:02d}" if isinstance(ts, dt.datetime) else ""
                setter_console.append({"year": d[0], "month": d[1],
                                       "d": f"{d[0]:04d}-{d[1]:02d}-{d[2]:02d}", "heure": heure,
                                       "setter": setter,
                                       "energie": parse_num(g("energie")),
                                       "audits": parse_num(g("audits")) or 0,
                                       "contactes": parse_num(g("contactes")) or 0,
                                       "accroches": parse_num(g("accroches")) or 0,
                                       "relances": parse_num(g("relances")) or 0,
                                       "reponses": parse_num(g("reponses")) or 0,
                                       "quali": parse_num(g("quali")) or 0,
                                       "proposes": parse_num(g("proposes")) or 0,
                                       "bookes": parse_num(g("bookes")) or 0,
                                       "objections": cell_str(g("objections"))[:400],
                                       "retours": cell_str(g("retours"))[:400]})
            continue

        if title == "EOD Setting Ecrit":
            hidx, header = find_header(iter(all_rows), ['total de "audit"'])
            if header is None:
                continue
            idx = {}
            for i, c in enumerate(header):
                n = norm(cell_str(c))
                if n.startswith("date du jour"):
                    idx["date"] = i
                elif 'total de "audit"' in n:
                    idx["audits"] = i
                elif "conversations qualifiees" in n:
                    idx["quali"] = i
                elif "rdv propose club" in n:
                    idx["prop_club"] = i
                elif "rdv propose valar" in n:
                    idx["prop_valar"] = i
                elif "rdv booke club" in n:
                    idx["bk_club"] = i
                elif "rdv booke valar" in n:
                    idx["bk_valar"] = i
            for r in all_rows[hidx + 1:]:
                def g(k):
                    i = idx.get(k)
                    return r[i] if i is not None and i < len(r) else None
                d = parse_date(g("date"))
                if not d:
                    continue
                dm_reports.append({"year": d[0], "month": d[1],
                                   "d": f"{d[0]:04d}-{d[1]:02d}-{d[2]:02d}",
                                   "audits_raw": cell_str(g("audits"))[:30],
                                   "audits": parse_num(g("audits")) or 0,
                                   "quali": parse_num(g("quali")) or 0,
                                   "proposes": (parse_num(g("prop_club")) or 0) + (parse_num(g("prop_valar")) or 0),
                                   "bookes": (parse_num(g("bk_club")) or 0) + (parse_num(g("bk_valar")) or 0)})
            continue

    out = {"calls": calls, "stripe": stripe, "settings": settings_rows,
           "setter_reports": setter_reports, "dm_reports": dm_reports,
           "setter_console": setter_console, "history": history, "csm": csm,
           "iclosed": iclosed_leads, "iclosed_claims": iclosed_claims,
           "wa_confirms": wa_confirms, "valar_claims": valar_claims}
    with open(out_path, "w") as f:
        json.dump(out, f, ensure_ascii=False)

    c26 = [c for c in calls if c["year"] == 2026]
    print(f"calls total={len(calls)} 2026={len(c26)}", file=sys.stderr)
    print("par tab:", Counter(c["tab"] for c in calls).most_common(), file=sys.stderr)
    print("par mois 2026:", dict(sorted(Counter(c["month"] for c in c26).items())), file=sys.stderr)
    print("ventes 2026:", Counter(c["vente"] for c in c26), file=sys.stderr)
    print(f"stripe={len(stripe)} total={sum(s['montant_ttc'] for s in stripe):.0f}", file=sys.stderr)
    print(f"settings={len(settings_rows)} setter={len(setter_reports)} dm={len(dm_reports)} eod_setter={len(setter_console)}", file=sys.stderr)
    print(f"confirmations whatsapp={len(wa_confirms)}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
