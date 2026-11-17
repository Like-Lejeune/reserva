"""Dessine le logo de Reserva : l'équerre de chantier et la coche du défaut levé.

Produit, dans le dossier donné :
  icon.svg         icône d'application (carré bleu)
  logo.svg         logo horizontal, texte bleu, pour fond clair
  logo-blanc.svg   logo horizontal, texte blanc, pour fond foncé
  concepts.html    planche de présentation
Le mot « reserva » est converti en tracés : il s'affiche pareil partout, sans police à charger.

Pour le refaire (autre nom, autres couleurs) :
    npm i @fontsource/barlow && pip install fonttools brotli
    python fabriquer_logo.py sortie/
Les PNG du site (icon-192.png, icon-512.png, icon-maskable-512.png, apple-touch-icon.png) se
tirent ensuite de icon.svg avec n'importe quel outil d'export (Inkscape, navigateur).
"""

import math
import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
FONT = Path("node_modules/@fontsource/barlow/files/barlow-latin-700-normal.woff")

NAVY = "#1f3a5f"
OCHRE = "#f4c26b"
WHITE = "#ffffff"


# ---------- la marque : équerre + coche, dans un carré de 512 ----------

def mark(ground: str = NAVY, square: str = OCHRE, check: str = WHITE, with_ground: bool = True) -> str:
    """Équerre (triangle rectangle évidé, avec graduations) et coche qui en sort."""
    x0, y0, size, t = 118, 124, 268, 46          # angle droit en bas à gauche, côté, épaisseur
    x1, y1 = x0 + size, y0 + size               # (x0, y1) est l'angle droit
    k = t * math.sqrt(2)
    inner = [(x0 + t, y0 + t + k), (x0 + t, y1 - t), (x1 - t - k, y1 - t)]
    outer = [(x0, y0), (x0, y1), (x1, y1)]
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in outer) + " Z " + \
        "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in inner) + " Z"
    # graduations sur le grand côté vertical, comme sur une vraie équerre
    ticks = "".join(
        f'<rect x="{x0 + 8:.0f}" y="{y:.0f}" width="{14 if i % 2 else 22}" height="6" rx="2" fill="{ground}"/>'
        for i, y in enumerate(range(y0 + 92, y1 - t - 10, 26)))
    check_path = "M232,250 L292,310 L408,150"
    parts = []
    if with_ground:
        parts.append(f'<rect width="512" height="512" rx="112" fill="{ground}"/>')
    parts.append(f'<path d="{d}" fill="{square}" fill-rule="evenodd"/>')
    parts.append(ticks)
    # liseré couleur du fond sous la coche : elle se détache nettement de l'équerre
    parts.append(f'<path d="{check_path}" fill="none" stroke="{ground}" stroke-width="88" stroke-linecap="round" stroke-linejoin="round"/>')
    parts.append(f'<path d="{check_path}" fill="none" stroke="{check}" stroke-width="50" stroke-linecap="round" stroke-linejoin="round"/>')
    return "".join(parts)


def icon_svg() -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="Reserva">{mark()}</svg>\n'


# ---------- le mot « reserva » en tracés ----------

def word_paths(text: str, size: float, x: float, baseline: float, fill: str, tracking: float = -0.01) -> tuple[str, float]:
    font = TTFont(FONT)
    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    upm = font["head"].unitsPerEm
    scale = size / upm
    out, cursor = [], x
    for ch in text:
        name = cmap[ord(ch)]
        pen = SVGPathPen(glyphs)
        # l'axe y des polices monte, celui du SVG descend : on retourne
        glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, cursor, baseline)))
        out.append(pen.getCommands())
        cursor += glyphs[name].width * scale + tracking * size
    return f'<path d="{" ".join(out)}" fill="{fill}"/>', cursor - x


def lockup_svg(text_color: str) -> str:
    """Marque + mot, côte à côte. Hauteur 128 ; la largeur suit le mot."""
    h = 128
    word, width = word_paths("reserva", 92, 152, 96, text_color)
    total = 152 + width + 6
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total:.0f} {h}" role="img" aria-label="Reserva">'
            f'<g transform="scale({h / 512})">{mark()}</g>{word}</svg>\n')


(OUT / "icon.svg").write_text(icon_svg())
(OUT / "logo.svg").write_text(lockup_svg(NAVY))
(OUT / "logo-blanc.svg").write_text(lockup_svg(WHITE))

# Planche de présentation : l'icône à plusieurs tailles, les deux logos, l'usage sur téléphone.
(OUT / "concepts.html").write_text(f"""<!doctype html><meta charset="utf-8">
<style>
body {{ margin:0; font-family: system-ui, sans-serif; background:#fff; color:#16202e; }}
.wrap {{ width: 1200px; padding: 48px; box-sizing: border-box; }}
h1 {{ font-size: 28px; margin: 0 0 6px; }} p {{ margin: 0 0 28px; color:#64707f; }}
.row {{ display:flex; gap:40px; align-items:flex-end; margin-bottom:40px; }}
.row figure {{ margin:0; text-align:center; font-size:13px; color:#64707f; }}
.band {{ display:flex; gap:0; margin-bottom:40px; }}
.band div {{ flex:1; padding:40px; display:flex; align-items:center; justify-content:center; }}
.phone {{ width: 260px; height: 160px; background: #e9ecf0; border-radius: 28px; display:grid;
  grid-template-columns: repeat(4, 1fr); gap: 14px; padding: 22px; box-sizing:border-box; }}
.phone span {{ display:block; width:46px; height:46px; border-radius:12px; background:#cfd5dc; }}
.phone img {{ width:46px; height:46px; }}
.swatch {{ display:flex; gap:16px; }} .swatch div {{ width:120px; font-size:13px; }}
.swatch i {{ display:block; height:56px; border-radius:10px; margin-bottom:6px; border:1px solid #dfe3e8; }}
</style>
<div class="wrap">
<h1>Reserva : proposition de logo</h1>
<p>L'équerre, l'outil de l'ingénieur sur le chantier, et la coche du défaut levé.</p>
<div class="row">
  <figure><img src="icon.svg" width="192"><figcaption>Icône d'application</figcaption></figure>
  <figure><img src="icon.svg" width="96"><figcaption>96 px</figcaption></figure>
  <figure><img src="icon.svg" width="48"><figcaption>48 px</figcaption></figure>
  <figure><img src="icon.svg" width="24"><figcaption>24 px</figcaption></figure>
  <figure><div class="phone"><span></span><span></span><img src="icon.svg"><span></span><span></span><span></span><span></span><span></span></div><figcaption>Sur l'écran d'accueil</figcaption></figure>
</div>
<div class="band">
  <div style="background:#fff;border:1px solid #dfe3e8"><img src="logo.svg" height="72"></div>
  <div style="background:{NAVY}"><img src="logo-blanc.svg" height="72"></div>
</div>
<div class="swatch">
  <div><i style="background:{NAVY}"></i>Bleu chantier {NAVY}</div>
  <div><i style="background:{OCHRE}"></i>Ocre sécurité {OCHRE}</div>
  <div><i style="background:#ffffff"></i>Blanc #ffffff</div>
  <div style="width:auto;padding-top:20px">Police du mot : Barlow Bold, inspirée de la signalisation routière.</div>
</div>
</div>
""")
print("ok", sorted(p.name for p in OUT.iterdir()))
