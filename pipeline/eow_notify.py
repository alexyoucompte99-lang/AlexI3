#!/usr/bin/env python3
"""Notifie sur Telegram les nouvelles lignes de l'onglet « EOW Console » du
classeur closing (rempli par la console via le pont Apps Script).

Usage: python3 eow_notify.py investisseurs30.xlsx ../.eow-count
Env : TELEGRAM_TOKEN, TELEGRAM_CHAT (sinon ne fait rien).
Le fichier d'état contient le nombre de lignes déjà notifiées (commité par le
workflow pour persister entre les runs).
"""
import json
import os
import sys
import urllib.parse
import urllib.request

import openpyxl


def send(token, chat, text):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=urllib.parse.urlencode({"chat_id": chat, "text": text}).encode(),
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.load(resp)
    if not out.get("ok"):
        raise RuntimeError(f"Telegram: {out}")


def main(xlsx_path, state_path):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT")
    if not (token and chat):
        print("pas de config Telegram, EOW non notifiés", file=sys.stderr)
        return
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    if "EOW Console" not in wb.sheetnames:
        print("onglet EOW Console absent (aucun EOW envoyé pour l'instant)", file=sys.stderr)
        return
    rows = [r for r in wb["EOW Console"].iter_rows(values_only=True) if any(r)]
    n = len(rows) - 1  # moins l'en-tête
    try:
        seen = int(open(state_path).read().strip())
    except Exception:
        seen = 0
    if n <= seen:
        print(f"EOW : rien de nouveau ({n} au total)", file=sys.stderr)
        return
    for r in rows[1 + seen:]:
        vals = [str(v).strip() if v is not None else "" for v in (list(r) + [""] * 9)[:9]]
        date, closer, energie, leads, good, hard, obj, need, free = vals
        text = (f"EOW reçu de {closer or '?'}\n\n"
                f"Énergie : {energie or '?'}/10 · Ressenti leads : {leads or '?'}/10\n\n"
                f"Ce qui a marché : {good or '·'}\n"
                f"Ce qui a bloqué : {hard or '·'}\n"
                f"Objection : {obj or '·'}\n"
                f"Besoin équipe : {need or '·'}\n"
                f"Autre : {free or '·'}")
        send(token, chat, text)
        print(f"EOW notifié : {closer}", file=sys.stderr)
    with open(state_path, "w") as f:
        f.write(str(n))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
