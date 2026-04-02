#!/usr/bin/env python3
"""
frontdoor brand asset renderer
Usage: python3 render-brand-assets.py [--force] [--workdir PATH]

Renders the frontdoor icon SVG design to PNG/ICO at all required sizes.
Requires: Pillow (pip install Pillow)

Output structure mirrors muxplex assets/branding/:
  icons/      — standalone icon at 16, 22, 24, 32, 48, 64, 128, 192, 256, 512, 1024
  favicons/   — favicon-16, favicon-32, favicon-48, apple-touch-icon (180), favicon.ico
  pwa/        — pwa-192, pwa-512
  lockup/     — icon+wordmark at 32h and 64h (dark and light)
"""

import argparse
import math
import struct
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("[ERROR] Pillow not installed. Run: pip install Pillow")

# ──────────────────────────────────────────────────────────────────────────────
# Argument parsing
# ──────────────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Render frontdoor brand assets")
parser.add_argument(
    "--force", action="store_true", help="Re-render even if output exists"
)
parser.add_argument(
    "--workdir", default=None, help="Base directory (default: parent of script)"
)
args = parser.parse_args()

WORKDIR = Path(args.workdir).resolve() if args.workdir else Path(__file__).parent.parent
ASSETS = WORKDIR / "assets" / "branding"
FORCE = args.force

if not ASSETS.exists():
    raise SystemExit(
        f"[ERROR] Cannot find {ASSETS}\nRun from the frontdoor/ directory or pass --workdir <path>"
    )

print(f"[workdir] {WORKDIR}")
print(f"[assets]  {ASSETS}")

# ──────────────────────────────────────────────────────────────────────────────
# Design constants (all in 64×64 design space; scaled up at render time)
# ──────────────────────────────────────────────────────────────────────────────

# Corner radius (from SVG: 2.059 units = how much the rounded corner cuts)
CORNER_RATIO = 2.059 / 64  # ~3.2% of icon size

# Window chrome
BORDER_RATIO = 2.745 / 64  # inner offset from edge
HEADER_BOTTOM = 15.786 / 64  # top of divider strip
BODY_START = 18.188 / 64  # bottom of divider strip

# Header dots
DOT_RADIUS = 2.917 / 64
DOT_Y = 9.265 / 64
DOT_X1 = 9.265 / 64  # green dot
DOT_X2 = 18.531 / 64  # neutral dot
DOT_X3 = 27.796 / 64  # blue dot

# Door (arch-top rectangle)
DOOR_X1 = 21.0 / 64
DOOR_X2 = 43.0 / 64
DOOR_ARCH_Y = 34.0 / 64  # y where arch tangent meets rect (arch center)
DOOR_BOTTOM = 58.0 / 64
DOOR_STROKE = 1.5 / 64
DOOR_HANDLE_X = 39.0 / 64
DOOR_HANDLE_Y = 44.0 / 64
DOOR_HANDLE_R = 2.0 / 64

# ──────────────────────────────────────────────────────────────────────────────
# Color palettes
# ──────────────────────────────────────────────────────────────────────────────


def h(hex_str):
    """Parse hex color to (R, G, B) tuple."""
    s = hex_str.lstrip("#")
    return tuple(int(s[i : i + 2], 16) for i in (0, 2, 4))


DARK = dict(
    bg=h("#0D1117"),
    chrome=h("#FFFFFF"),
    dot1=h("#34C759"),  # Apple green
    dot2=h("#FFFFFF"),  # white
    dot3=h("#007AFF"),  # Apple blue
    door_fill=h("#1A1F2B"),
    door_stroke=h("#FFFFFF"),
    handle=h("#007AFF"),
)

LIGHT = dict(
    bg=h("#F5F5F7"),
    chrome=h("#1D1D1F"),
    dot1=h("#34C759"),
    dot2=h("#8E8E93"),  # neutral gray (visible on light bg)
    dot3=h("#007AFF"),
    door_fill=h("#FFFFFF"),
    door_stroke=h("#1D1D1F"),
    handle=h("#007AFF"),
)

# ──────────────────────────────────────────────────────────────────────────────
# Rendering helpers
# ──────────────────────────────────────────────────────────────────────────────

OVERSAMPLE = 4  # render at OVERSAMPLE× then scale down for anti-aliasing


def rgba(color_tuple, alpha=255):
    return color_tuple + (alpha,)


def door_polygon(S, n=128):
    """
    Build the arch-top door polygon points in render space.

    The door goes from (DOOR_X1*S, DOOR_BOTTOM*S) up the left side,
    arches over the top (semicircle with radius = half door width),
    then down the right side to (DOOR_X2*S, DOOR_BOTTOM*S).
    """
    cx = (DOOR_X1 + DOOR_X2) / 2 * S
    r = (DOOR_X2 - DOOR_X1) / 2 * S  # arch radius = half door width
    ay = DOOR_ARCH_Y * S  # y at arch tangent / circle center
    ybot = DOOR_BOTTOM * S

    pts = []
    # Start at bottom-left
    pts.append((DOOR_X1 * S, ybot))
    # Arch: angle sweeps from π (left) down to 0 (right), using y = ay - r*sin(angle)
    # so that sin(π/2) = max → topmost point at (cx, ay - r)
    for i in range(n + 1):
        angle = math.pi * (1.0 - i / n)
        x = cx + r * math.cos(angle)
        y = ay - r * math.sin(angle)
        pts.append((x, y))
    # Finish at bottom-right (arch already ends here, but explicit is cleaner)
    pts.append((DOOR_X2 * S, ybot))
    return pts


def render_icon(size, palette, oversample=OVERSAMPLE):
    """
    Render a single icon image at `size`×`size` pixels.

    Draws at size*oversample, then scales down with LANCZOS.
    Returns a PIL Image in RGBA mode.
    """
    S = size * oversample
    p = palette

    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    corner_r = max(1, round(CORNER_RATIO * S))
    border_w = max(1, round(BORDER_RATIO * S))
    hdr_bot = round(HEADER_BOTTOM * S)
    body_top = round(BODY_START * S)

    # ── Step 1: white/chrome base (fills everything, acts as chrome) ──
    draw.rounded_rectangle(
        [0, 0, S - 1, S - 1], radius=corner_r, fill=rgba(p["chrome"])
    )

    # ── Step 2: dark header fill (inside border, above divider) ──
    draw.rectangle([border_w, border_w, S - border_w, hdr_bot], fill=rgba(p["bg"]))

    # ── Step 3: dark body fill (inside border, below divider) ──
    draw.rectangle([border_w, body_top, S - border_w, S - border_w], fill=rgba(p["bg"]))

    # ── Step 4: header dots ──
    dot_r = max(1, round(DOT_RADIUS * S))

    def dot(cx_ratio, color_key):
        cx = round(cx_ratio * S)
        cy = round(DOT_Y * S)
        draw.ellipse(
            [cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=rgba(p[color_key])
        )

    dot(DOT_X1, "dot1")
    dot(DOT_X2, "dot2")
    dot(DOT_X3, "dot3")

    # ── Step 5: door polygon ──
    pts = door_polygon(S)
    draw.polygon(pts, fill=rgba(p["door_fill"]))

    # Door outline — drawn as a filled polygon slightly larger to simulate stroke
    stroke_w = max(1, round(DOOR_STROKE * S))
    draw.polygon(pts, outline=rgba(p["door_stroke"]), width=stroke_w)

    # ── Step 6: door handle / knob ──
    hx = round(DOOR_HANDLE_X * S)
    hy = round(DOOR_HANDLE_Y * S)
    hr = max(1, round(DOOR_HANDLE_R * S))
    draw.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=rgba(p["handle"]))

    # ── Step 7: apply rounded-corner mask ──
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, S - 1, S - 1], radius=corner_r, fill=255
    )
    img.putalpha(mask)

    # ── Scale down with LANCZOS for anti-aliasing ──
    return img.resize((size, size), Image.Resampling.LANCZOS)


# ──────────────────────────────────────────────────────────────────────────────
# ICO file builder (minimal multi-size ICO without external deps)
# ──────────────────────────────────────────────────────────────────────────────


def _png_bytes(img):
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def make_ico(images):
    """
    Build a minimal ICO file from a list of PIL images.
    images: list of PIL RGBA images (different sizes)
    Returns bytes of the ICO file.
    """
    import io

    n = len(images)
    png_chunks = [_png_bytes(img) for img in images]

    header_size = 6 + 16 * n  # ICONDIR + n ICONDIRENTRY
    data_offset = header_size

    entries = []
    for img, data in zip(images, png_chunks):
        w, h = img.size
        entries.append((w, h, data_offset, len(data)))
        data_offset += len(data)

    buf = io.BytesIO()
    # ICONDIR
    buf.write(struct.pack("<HHH", 0, 1, n))
    # ICONDIRENTRY × n
    for w, h, offset, size in entries:
        wbyte = w if w < 256 else 0
        hbyte = h if h < 256 else 0
        buf.write(struct.pack("<BBBBHHII", wbyte, hbyte, 0, 0, 1, 32, size, offset))
    # PNG data
    for data in png_chunks:
        buf.write(data)
    return buf.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
# Output paths
# ──────────────────────────────────────────────────────────────────────────────

ICONS_DIR = ASSETS / "icons"
FAVICONS_DIR = ASSETS / "favicons"
PWA_DIR = ASSETS / "pwa"
LOCKUP_DIR = ASSETS / "lockup"

for d in [ICONS_DIR, FAVICONS_DIR, PWA_DIR, LOCKUP_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def save(img, path, force=FORCE):
    p = Path(path)
    if p.exists() and not force:
        print(f"  [skip] {p.relative_to(WORKDIR)}")
        return
    img.save(str(p), optimize=True)
    kb = p.stat().st_size // 1024
    print(f"  [ok]   {p.relative_to(WORKDIR)} ({kb}KB)")


def save_ico(images, path, force=FORCE):
    p = Path(path)
    if p.exists() and not force:
        print(f"  [skip] {p.relative_to(WORKDIR)}")
        return
    p.write_bytes(make_ico(images))
    kb = p.stat().st_size // 1024
    print(f"  [ok]   {p.relative_to(WORKDIR)} ({kb}KB)")


# ──────────────────────────────────────────────────────────────────────────────
# Render all assets
# ──────────────────────────────────────────────────────────────────────────────

print("\n── Icon sizes ──────────────────────────────────────────────────────────")
ICON_SIZES = [16, 22, 24, 32, 48, 64, 128, 192, 256, 512, 1024]

for sz in ICON_SIZES:
    img_dark = render_icon(sz, DARK)
    save(img_dark, ICONS_DIR / f"frontdoor-icon-{sz}.png")

print("\n── Favicons ────────────────────────────────────────────────────────────")
fav16 = render_icon(16, DARK)
fav32 = render_icon(32, DARK)
fav48 = render_icon(48, DARK)
fav180 = render_icon(180, LIGHT)  # apple-touch-icon on white bg

save(fav16, FAVICONS_DIR / "favicon-16.png")
save(fav32, FAVICONS_DIR / "favicon-32.png")
save(fav48, FAVICONS_DIR / "favicon-48.png")
save(fav180, FAVICONS_DIR / "apple-touch-icon.png")
save_ico([fav16, fav32, fav48], FAVICONS_DIR / "favicon.ico")

print("\n── PWA ─────────────────────────────────────────────────────────────────")
save(render_icon(192, DARK), PWA_DIR / "pwa-192.png")
save(render_icon(512, DARK), PWA_DIR / "pwa-512.png")

print("\n── Lockup thumbnails ───────────────────────────────────────────────────")


def render_lockup_thumb(icon_h, palette):
    """
    Render icon-only lockup thumbnail at given icon height.
    (Full text lockup requires a proper font; this gives the icon at scale.)
    """
    return render_icon(icon_h, palette)


for h_px in [32, 64]:
    save(render_lockup_thumb(h_px, DARK), LOCKUP_DIR / f"lockup-on-dark-{h_px}.png")
    save(render_lockup_thumb(h_px, LIGHT), LOCKUP_DIR / f"lockup-on-light-{h_px}.png")

print("\n── Done ────────────────────────────────────────────────────────────────")
print(f"All assets written to {ASSETS.relative_to(WORKDIR)}/")
print("To generate full lockup PNGs with the 'frontdoor' wordmark, run with")
print("a system that has Urbanist or Inter installed and render via cairosvg:")
print("  cairosvg assets/branding/svg/lockup/lockup-on-dark.svg -o out.png -W 480")
