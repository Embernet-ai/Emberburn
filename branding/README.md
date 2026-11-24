# Emberburn official brand assets

Patrick's pick, 2026-11-24: concept A, Signal flame (a flame over a signal wave). Source concepts are in `work/out/brand/marks-2026-11-23/`. These files are final: use them byte for byte, size by height only, never recolor, redraw or approximate.

Spelling is Emberburn.

## Files

| File | What it is |
|---|---|
| `mark.svg` | The mark in ember `#D92D20`, plain filled paths, `viewBox="0 0 100 100"`, no strokes, no evenodd. |
| `mark-white.svg` | The same mark in white `#FFFFFF`, for ember or dark backgrounds. |
| `mark-32.svg`, `mark-16.svg` | Small-size cuts, redrawn heavier so the mark holds at 32 px and 16 px. Use these at or below those sizes. |
| `app-icon.svg` | The white mark on an ember rounded square (corner radius 22.9 percent). |
| `app-icon-32.svg`, `app-icon-16.svg` | The same app icon with the small-size cuts. |
| `wordmark.svg` | Mark plus the name, text converted to outlines so it needs no font. "Ember" in ember, "burn" in ink. For white and light backgrounds. |
| `wordmark-dark.svg` | The same lockup with the ink part in white, for dark backgrounds. |
| `png/mark-N.png` | The ember mark at N = 16, 32, 48, 64, 128, 192, 256, 512 and 1024 px square, transparent. 16 and 32 use the small cuts. |
| `png/mark-white-N.png` | The white mark at the same sizes. |
| `png/app-icon-N.png` | The app icon at the same sizes. 16 and 32 use the small cuts. |
| `png/wordmark-256h.png`, `png/wordmark-dark-256h.png` | The lockups at 256 px tall. |
| `favicon.ico` | 16, 32 and 48 px app icon, for the web UI. |

## Colors

Tokens are `Embernet-ai/embernet-design` at `6a0f44d` (`tokens.css`, `tokens.json`).

| Use | Token | Value |
|---|---|---|
| Mark, "Ember" in the wordmark, app icon ground | `--en-ember` | `#D92D20` |
| The rest of the name on light | `--en-ink` | `#101828` |
| Mark on ember, name on dark | `--en-on-ember` | `#FFFFFF` |

## Wordmark type

The outlines are Source Sans 3 Bold (Adobe, SIL Open Font License 1.1, from `@fontsource/source-sans-3` 5.3.1). It was chosen as the closest letterforms and weight to the official EmberNet wordmark at `Embernet-ai/embernet.ai/public/brand/embernet-logo.png`, which stays the EmberNet logo and is never replaced by these.

## How these were made

The mark paths come from the concept file, with every stroke and evenodd fill flattened to plain filled outlines (Skia path ops via `skia-pathops`), then centered in the 100 unit box at 92 percent. The build script is `work/out/brand/official-2026-11-24/build/`.
