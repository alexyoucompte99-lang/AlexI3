#!/usr/bin/env python3
"""Chiffre une page HTML avec un code d'accès -> page autonome qui se déchiffre
dans le navigateur (AES-256-CBC via openssl, PBKDF2 200k itérations).

Usage: python3 encrypt_page.py <page.html> <sortie.html> <code> <titre>
"""
import base64
import subprocess
import sys

SHELL = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>__TITRE__</title>
<style>
  body { margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:#f7efe4; color:#262019; font-family:"Avenir Next",-apple-system,"Segoe UI",sans-serif; }
  .box { background:#fdfbf6; border:1px solid #e9ddc9; border-radius:14px; padding:28px 30px; max-width:340px; text-align:center; }
  h1 { font-family:Georgia,serif; font-size:21px; margin:0 0 4px; }
  p { font-size:13px; color:#5d5344; margin:0 0 16px; }
  input { width:100%; box-sizing:border-box; font-size:15px; padding:10px 12px; border:1px solid #d4c7b2;
          border-radius:10px; background:#fff; color:#262019; text-align:center; }
  button { margin-top:12px; width:100%; font-size:14px; font-weight:600; padding:10px; border-radius:999px;
           border:none; background:#241d15; color:#f7efe4; cursor:pointer; }
  button:hover { background:#a34524; color:#fff; }
  .err { color:#c03a30; font-size:12.5px; margin-top:10px; display:none; }
</style>
</head>
<body>
<div class="box">
  <h1>__TITRE__</h1>
  <p>Page protégée. Entre le code d'accès.</p>
  <input type="password" id="code" placeholder="Code d'accès" autofocus>
  <button id="go">Ouvrir</button>
  <div class="err" id="err">Mauvais code.</div>
</div>
<script>
const PAYLOAD = "__PAYLOAD__";
async function decrypt(pass) {
  const raw = Uint8Array.from(atob(PAYLOAD), c => c.charCodeAt(0));
  const salt = raw.slice(8, 16), data = raw.slice(16);
  const km = await crypto.subtle.importKey("raw", new TextEncoder().encode(pass), "PBKDF2", false, ["deriveBits"]);
  const bits = new Uint8Array(await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt, iterations: 200000, hash: "SHA-256" }, km, 48 * 8));
  const key = await crypto.subtle.importKey("raw", bits.slice(0, 32), "AES-CBC", false, ["decrypt"]);
  const plain = await crypto.subtle.decrypt({ name: "AES-CBC", iv: bits.slice(32, 48) }, key, data);
  return new TextDecoder().decode(plain);
}
async function tryOpen(pass) {
  try {
    const html = await decrypt(pass);
    sessionStorage.setItem("i3-code", pass);
    document.open(); document.write(html); document.close();
  } catch (e) {
    sessionStorage.removeItem("i3-code");
    document.getElementById("err").style.display = "block";
  }
}
document.getElementById("go").addEventListener("click", () => tryOpen(document.getElementById("code").value.trim()));
document.getElementById("code").addEventListener("keydown", e => { if (e.key === "Enter") tryOpen(e.target.value.trim()); });
const saved = sessionStorage.getItem("i3-code");
if (saved) tryOpen(saved);
</script>
</body>
</html>
"""


def main(src, dst, code, titre):
    enc = subprocess.run(
        ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-md", "sha256",
         "-salt", "-in", src, "-pass", "pass:" + code],
        capture_output=True, check=True).stdout
    payload = base64.b64encode(enc).decode()
    out = SHELL.replace("__TITRE__", titre).replace("__PAYLOAD__", payload)
    with open(dst, "w") as f:
        f.write(out)
    print(f"OK -> {dst} ({len(out) // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
