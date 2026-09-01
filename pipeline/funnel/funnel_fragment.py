#!/usr/bin/env python3
"""Transforme la console funnel autonome en un fragment intégrable dans la
console closing (onglet Funnel, sous-onglets Ancien / Nouveau / Les 2).

La source de vérité reste funnel-template.html (la console funnel telle qu'elle
existe dans le projet console-suivi-i3) : ce script la ré-encapsule à chaque
build, donc une évolution de la console funnel se répercute sans réécriture.

Ce qu'il fait :
  - CSS : jette les règles globales que la console closing fournit déjà (:root et
    ses variantes sombres, body), renomme en fx-* les classes qui existent des
    deux côtés (tab, card, num…), puis préfixe chaque sélecteur par #fxRoot pour
    que rien ne déborde sur le reste de la console.
  - Markup : retire l'en-tête autonome (titre + bouton Actualiser : la console
    closing a les siens) en gardant la ligne d'horodatage que le JS remplit.
    Sans #btnRefresh, le setupRefresh du funnel sort tout seul (if (!btn) return),
    donc aucun second minuteur d'auto-reload ne tourne.
  - JS : mêmes renommages, querySelectorAll limités au conteneur, et le tout
    (données comprises) enfermé dans une IIFE : aucune variable globale ajoutée.

Chaque étape est vérifiée à la fin : s'il reste une classe en collision ou un
placeholder non substitué, le script échoue au lieu de produire une page cassée.

Usage : python3 funnel_fragment.py funnel-template.html data-block.js out.css out.html
"""
import os
import re
import sys

# classes définies des deux côtés : renommées fx-* côté funnel pour que les deux
# feuilles de style ne se marchent pas dessus
COLLIDE = ["lede-top", "top-right", "filterbar", "eyebrow", "badge", "delta",
           "kpis", "card", "tabs", "lede", "wrap", "num", "sub", "val", "lbl",
           "tab", "top", "na"]
COLLIDE_SET = set(COLLIDE)
ROOT = "#fxRoot"

# règles globales fournies par la console closing (palette, reset du body) ou
# inutiles une fois le funnel dans un onglet (.wrap = la mise en page de la page)
DROP_EXACT = {"body", ".wrap", ".fx-wrap"}

HEAD_REPL = ('<p class="fxhead"><span class="stamp" id="headStamp">Relevé</span>'
             '<span id="headSources"></span></p>')
EXTRA_CSS = (ROOT + " .fxhead { display: flex; flex-wrap: wrap; align-items: center; gap: 10px;"
             " font-size: 12.5px; color: var(--ink-2); margin: 0 0 10px; }\n")


def split_blocks(css):
    """Découpe une feuille de style en blocs (prélude, corps) de premier niveau."""
    blocks, buf, depth, prelude = [], "", 0, ""
    for ch in css:
        if ch == "{":
            depth += 1
            if depth == 1:
                prelude, buf = buf.strip(), ""
            else:
                buf += ch
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blocks.append((prelude, buf))
                buf = ""
            else:
                buf += ch
        else:
            buf += ch
    return blocks


def keep(prelude):
    p = prelude.strip()
    # la palette (:root, :root[data-theme=dark], :root:not(...)) vient du closing
    return not (p.startswith(":root") or p in DROP_EXACT)


def scope(prelude):
    return ", ".join(ROOT + " " + s.strip() for s in prelude.split(",") if s.strip())


# un point précédé d'un chiffre est une décimale (0.85rem), pas une classe ;
# partout ailleurs (« .num », « td.num », « .delta.na ») c'est bien un sélecteur
CLS_RE = r"(?<!\d)\.%s(?![\w-])"


def rename_css(css):
    for name in COLLIDE:
        css = re.sub(CLS_RE % re.escape(name), ".fx-" + name, css)
    return css


def rename_class_attrs(txt):
    def sub(m):
        toks = ["fx-" + t if t in COLLIDE_SET else t for t in m.group(1).split()]
        return 'class="' + " ".join(toks) + '"'
    return re.sub(r'class="([^"]*)"', sub, txt)


def rename_js(js):
    for name in COLLIDE:
        js = re.sub(r"(querySelectorAll?\(')\." + re.escape(name) + r"(?![\w-])",
                    r"\1.fx-" + name, js)
        js = re.sub(r"(classList\.\w+\(')" + re.escape(name) + r"(?=')",
                    r"\1fx-" + name, js)
    return js


def build_css(raw):
    raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    raw = rename_css(raw)
    out = []
    for prelude, body in split_blocks(raw):
        if prelude.startswith("@"):
            # la palette sombre est déjà gérée par la console closing
            if "prefers-color-scheme" in prelude:
                continue
            inner = [scope(p) + " {" + b + "}"
                     for p, b in split_blocks(body) if keep(p)]
            if inner:
                out.append(prelude + " {\n" + "\n".join(inner) + "\n}")
        elif keep(prelude):
            out.append(scope(prelude) + " {" + body + "}")
    return EXTRA_CSS + "\n".join(out) + "\n"


def main(tpl_path, data_path, css_out, html_out):
    tpl = open(tpl_path, encoding="utf-8").read()
    data = open(data_path, encoding="utf-8").read().strip()

    css_raw = re.search(r"<style>(.*?)</style>", tpl, re.S).group(1)
    rest = tpl.split("</style>", 1)[1]
    markup, js = rest.split("<script>", 1)
    js = js.rsplit("</script>", 1)[0]

    css = build_css(css_raw)

    markup = rename_class_attrs(markup)
    # en-tête autonome (titre + bouton Actualiser) remplacé par la seule ligne
    # d'horodatage : la console closing porte déjà titre et bouton de MAJ
    markup, n = re.subn(r'<header class="fx-top">.*?</header>', HEAD_REPL, markup, flags=re.S)
    assert n == 1, f"en-tête du funnel introuvable ({n} remplacement)"
    markup = markup.replace('id="kpis"', 'id="fxKpis"')

    js = rename_class_attrs(rename_js(js))
    assert "getElementById('kpis')" in js, "getElementById('kpis') attendu dans le JS funnel"
    js = js.replace("getElementById('kpis')", "getElementById('fxKpis')")
    js = js.replace("document.querySelectorAll(", "FXROOT.querySelectorAll(")
    assert "__DATA__" in js
    js = js.replace("__DATA__", data.replace("</", "<\\/"))

    frag = (markup.strip() + "\n<script>\n(function () {\n"
            "  var FXROOT = document.getElementById('fxRoot');\n"
            "  if (!FXROOT) return;\n" + js + "\n})();\n</script>\n")

    # garde-fous : rien ne doit fuir hors du conteneur, rien ne doit rester à substituer
    leftovers = [n for n in COLLIDE if re.search(CLS_RE % re.escape(n), css)]
    assert not leftovers, f"classes non renommées dans le CSS : {leftovers}"
    for m in re.finditer(r'class="([^"]*)"', frag):
        bad = [t for t in m.group(1).split() if t in COLLIDE_SET]
        assert not bad, f"classe en collision dans le fragment : {bad} ({m.group(0)[:60]})"
    assert "document.querySelectorAll" not in frag, "querySelectorAll non limité au conteneur"
    assert "__DATA__" not in frag and "id=\"btnRefresh\"" not in frag

    open(css_out, "w", encoding="utf-8").write(css)
    open(html_out, "w", encoding="utf-8").write(frag)
    print(f"funnel_fragment: {os.path.basename(css_out)} {len(css)//1024} KB, "
          f"{os.path.basename(html_out)} {len(frag)//1024} KB")


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) != 4:
        sys.exit("usage: funnel_fragment.py funnel-template.html data-block.js out.css out.html")
    main(*a)
