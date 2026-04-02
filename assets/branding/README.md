# frontdoor brand assets

Visual identity for **frontdoor** — developer-host SSO gateway and service dashboard.

---

## Design language

The frontdoor icon follows the same visual grammar as the sibling **muxplex** project:
a dark app-window chrome with a thin header bar and three coloured dots, surrounding
content that represents what the app _does_.

| Element | frontdoor | muxplex |
|---------|-----------|---------|
| Header dot 1 | Green `#34C759` (services up) | Amber `#F1A640` (notifications) |
| Header dot 2 | White `#FFFFFF` (neutral) | White `#FFFFFF` (neutral) |
| Header dot 3 | Blue `#007AFF` (auth/primary) | Cyan `#00D9F5` (primary accent) |
| Body content | Arch-top door + knob | 2×2 tmux pane grid |
| Wordmark accent | `door` in `#007AFF` | `plex` in `#00D9F5` |

The door silhouette is a semicircular-arch-top rectangle centred in the body area,
recalling the "front door" metaphor — one authenticated entry point to your host.

---

## File structure

```
assets/branding/
├── svg/                     ← canonical source files (edit these)
│   ├── icon/
│   │   ├── frontdoor-icon-dark.svg
│   │   └── frontdoor-icon-light.svg
│   ├── lockup/              ← icon + "frontdoor" wordmark
│   │   ├── lockup-on-dark.svg
│   │   └── lockup-on-light.svg
│   └── wordmark/            ← text-only wordmark
│       ├── wordmark-on-dark.svg
│       └── wordmark-on-light.svg
├── icons/                   ← standalone icon PNGs
│   ├── frontdoor-icon-16.png  … 22, 24, 32, 48, 64, 128, 192, 256, 512, 1024
├── favicons/
│   ├── favicon-16.png
│   ├── favicon-32.png
│   ├── favicon-48.png
│   ├── apple-touch-icon.png  (180×180, light mode)
│   └── favicon.ico           (multi-size: 16/32/48)
├── pwa/
│   ├── pwa-192.png
│   └── pwa-512.png
├── lockup/                  ← icon-only lockup thumbnails (full lockup via SVG)
│   ├── lockup-on-dark-32.png
│   ├── lockup-on-dark-64.png
│   ├── lockup-on-light-32.png
│   └── lockup-on-light-64.png
├── og/
│   ├── og-dark.png           (1200×630 social preview, dark)
│   └── og-light.png          (1200×630 social preview, light)
├── tokens.json              ← design tokens (colours, type, spacing, motion)
└── README.md                ← this file
```

---

## Regenerating PNGs

All icon PNGs are generated from the PIL render script:

```bash
# From the frontdoor/ project root:
python3 scripts/render-brand-assets.py

# Force re-render (overwrite existing):
python3 scripts/render-brand-assets.py --force
```

**Requirements:** Python 3.9+, `Pillow` (`pip install Pillow`).

For full-lockup PNGs with the "frontdoor" wordmark rendered from SVG (requires
the Urbanist or Inter font):

```bash
pip install cairosvg
cairosvg assets/branding/svg/lockup/lockup-on-dark.svg -o out.png -W 480
```

---

## Usage

### Web favicon (HTML `<head>`)

```html
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png">
<link rel="shortcut icon" href="/favicon.ico">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
```

### PWA `manifest.json`

```json
{
  "name": "frontdoor",
  "short_name": "frontdoor",
  "icons": [
    { "src": "/pwa-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/pwa-512.png", "sizes": "512x512", "type": "image/png" }
  ],
  "theme_color": "#0D1117",
  "background_color": "#0D1117"
}
```

### CSS tokens

Add `tokens.json` to your design tooling, or reference values directly:

| Token | Dark | Light | Use |
|-------|------|-------|-----|
| accent blue | `#007AFF` | `#007AFF` | Buttons, links, focus |
| accent green | `#34C759` | `#34C759` | Service up indicator |
| accent red | `#FF3B30` | `#FF3B30` | Service down / error |
| bg base | `#000000` | `#F5F5F7` | Page background |
| text primary | `#F5F5F7` | `#1D1D1F` | Headings, body |

---

## Colours at a glance

| Swatch | Hex | Role |
|--------|-----|------|
| 🟦 | `#007AFF` | Apple blue — primary accent, auth, links |
| 🟢 | `#34C759` | Apple green — service running, success |
| 🔴 | `#FF3B30` | Apple red — service down, error |
| 🟡 | `#FF9500` | Apple yellow — warning |
| ⬛ | `#0D1117` | Icon / body background (dark) |
| ⬜ | `#F5F5F7` | Icon / body background (light) |
