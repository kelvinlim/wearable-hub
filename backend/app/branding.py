"""Shared UMN-branded server-rendered HTML shell.

Extracted from `routers/enroll.py` so the subject-facing enrollment flow, the public
homepage, and the privacy policy all render with one consistent shell (maroon #7A0019 /
gold #FFCC33). Server-rendered so subjects need no JS app and so the homepage / privacy
URLs Google's OAuth review checks are plain, publicly reachable HTML.
"""

from fastapi.responses import HTMLResponse

# UMN palette. The "M" tile is a stylized placeholder — drop the official UMN wordmark in
# to replace it.
STYLE = """
:root{--maroon:#7A0019;--gold:#FFCC33}
*{box-sizing:border-box}
body{font-family:'Open Sans',system-ui,-apple-system,sans-serif;margin:0;background:#f5f5f7;color:#1c1f26;line-height:1.6}
.bar{background:var(--maroon);color:#fff;display:flex;align-items:center;gap:.8rem;padding:.9rem 1.25rem;border-bottom:4px solid var(--gold)}
.bar .m{display:inline-flex;width:36px;height:36px;background:var(--gold);color:var(--maroon);border-radius:7px;align-items:center;justify-content:center;font-weight:800;font-size:1.2rem}
.bar .t b{font-size:1.05rem}
.bar .t span{display:block;font-size:.78rem;opacity:.85}
.wrap{max-width:40rem;margin:2.5rem auto;padding:0 1.25rem}
.card{background:#fff;border:1px solid #e3e3e8;border-radius:14px;padding:1.75rem 2rem;box-shadow:0 4px 18px rgba(0,0,0,.04)}
h1{font-size:1.5rem;color:var(--maroon);margin:0 0 .6rem}
h2{font-size:1.15rem;color:var(--maroon);margin:1.6rem 0 .4rem}
.lead{font-size:1.05rem;color:#3a3d45}
.steps{font-weight:600;margin:1.1rem 0 .25rem}
ol{padding-left:1.2rem;margin:.25rem 0}ol li{margin:.3rem 0}
ul{padding-left:1.2rem;margin:.4rem 0}ul li{margin:.25rem 0}
.note{font-size:.92rem;color:#5a5e69;background:#faf7ee;border:1px solid #f0e6c8;border-radius:10px;padding:.8rem 1rem;margin:1.25rem 0}
.disclosure{font-size:.95rem;color:#3a3d45;background:#fff;border:1px solid var(--gold);border-left:5px solid var(--maroon);border-radius:10px;padding:.9rem 1.1rem;margin:1.25rem 0}
form{display:flex;gap:.6rem;flex-wrap:wrap;margin-top:1rem}
input{padding:.7rem .85rem;font-size:1.05rem;border:1px solid #c9ccd4;border-radius:8px;flex:1;min-width:13rem;text-transform:uppercase;letter-spacing:.08em}
input:focus{outline:none;border-color:var(--maroon);box-shadow:0 0 0 3px rgba(122,0,25,.15)}
button{padding:.7rem 1.4rem;font-size:1.05rem;font-weight:700;cursor:pointer;background:var(--maroon);color:#fff;border:0;border-radius:8px}
button:hover{background:#5a0013}
.btn{display:inline-block;text-decoration:none;padding:.7rem 1.4rem;font-size:1.05rem;font-weight:700;background:var(--maroon);color:#fff;border-radius:8px;margin-top:1rem}
.err{color:#b00020;font-weight:600;margin:.75rem 0 0}
.foot{text-align:center;color:#8a8f9a;font-size:.8rem;margin-top:1.5rem}
.muted{color:#8a8f9a;font-size:.85rem}
a{color:var(--maroon)}
"""


def page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    """Wrap `body` HTML in the UMN-branded document shell."""
    html = (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{title} — University of Minnesota</title>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link href='https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap' rel='stylesheet'>"
        f"<style>{STYLE}</style></head><body>"
        "<div class='bar'><span class='m'>M</span>"
        "<div class='t'><b>University of Minnesota</b>"
        "<span>Wearable Hub — research data sharing</span></div></div>"
        f"<div class='wrap'><div class='card'>{body}</div>"
        "<div class='foot'>Version 1.0 · Questions? Contact your study staff.</div></div>"
        "</body></html>"
    )
    return HTMLResponse(html, status_code=status_code)
