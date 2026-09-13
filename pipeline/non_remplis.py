#!/usr/bin/env python3
"""Message Telegram du matin : les calls non remplis des 3 derniers jours (J-3 → J-1).

Usage: python3 non_remplis.py [--dry-run] [--refresh] [--date AAAA-MM-JJ] [--jours N]
Même règle que l'onglet « À remplir » de la console closing : show-up vide, ou
présent sans résultat. Tous les closers. Lit data.json (parse_xlsx.py).
Envoyé chaque matin par pilotage.yml (AlexI3), après la prise de recul.
"""
import datetime as dt
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from brief_bilan import PARIS, b, esc, send_html, tg_config  # noqa: E402

CONSOLE_URL = "https://alexyoucompte99-lang.github.io/AlexI3/closing/"
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def non_remplis(calls, today, nb_jours=3):
    frm = (today - dt.timedelta(days=nb_jours)).isoformat()
    to = (today - dt.timedelta(days=1)).isoformat()
    out = []
    for c in calls:
        d = c.get("date")
        if not d or not (frm <= d <= to):
            continue
        s, v = (c.get("show_up") or "").upper(), (c.get("vente") or "").strip()
        if not s or (s == "OUI" and not v):
            out.append(c)
    return out, frm, to


def fdate(iso):
    d = dt.date.fromisoformat(iso)
    return f"{JOURS[d.weekday()]} {d:%d/%m}"


def build(calls, today, nb_jours=3):
    todo, frm, to = non_remplis(calls, today, nb_jours)
    periode = f"{fdate(frm)} → {fdate(to)}"
    if not todo:
        return f"✅ {b('CALLS NON REMPLIS')}\n{periode}\n\nTout est rempli, rien à relancer."
    par_closer = {}
    for c in todo:
        par_closer.setdefault(" ".join((c.get("closer") or "Sans closer").split()), []).append(c)
    lines = [f"📋 {b('CALLS NON REMPLIS')}", periode, "", f"{b(len(todo))} call{'s' if len(todo) > 1 else ''} à remplir"]
    for name in sorted(par_closer, key=lambda n: (-len(par_closer[n]), n)):
        mine = sorted(par_closer[name], key=lambda c: (c["date"], c.get("hour") or ""))
        lines += ["", f"{b(esc(name))} ({len(mine)})"]
        for c in mine:
            h = (c.get("hour") or "").replace(":", "h")
            detail = " · présent, résultat manquant" if (c.get("show_up") or "").upper() == "OUI" else ""
            nom = esc((c.get("prospect") or "").strip() or "(sans nom)")
            lines.append(f"· {fdate(c['date'])}{' ' + h if h else ''} · {nom}{detail}")
    lines += ["", f"👉 <a href=\"{CONSOLE_URL}\">Onglet À remplir de la console</a>"]
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    if "--refresh" in args:
        r = subprocess.run([sys.executable, os.path.join(HERE, "refresh_data.py"), "--quiet"], cwd=HERE)
        if r.returncode != 0:
            print("⚠ refresh partiel : on part avec les données disponibles", file=sys.stderr)
    calls = json.load(open(os.path.join(HERE, "data.json")))["calls"]
    today = dt.datetime.now(PARIS).date()
    if "--date" in args:
        today = dt.date.fromisoformat(args[args.index("--date") + 1])
    nb = int(args[args.index("--jours") + 1]) if "--jours" in args else 3
    msg = build(calls, today, nb)
    print(msg)
    if "--dry-run" in args:
        return
    token, chat = tg_config()
    send_html(token, chat, msg)
    print("✓ calls non remplis envoyés sur Telegram")


if __name__ == "__main__":
    main()
