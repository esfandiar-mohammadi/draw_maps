# Test corpus — Reddit battlemaps (2026-07-14)

Downloaded from Reddit (via browser, since the API blocks this IP) for **local
wall-detection testing only**. Each map is © its creator; do NOT redistribute.
If this repo ever goes public, delete `maps/` and keep only these URLs + hashes.

| file | source (i.redd.it) | subreddit | style |
|---|---|---|---|
| map01 | 3hrm78ikqtif1.png | r/battlemaps | outdoor forest path (organic) |
| map02 | 5hsf6yxnkvkf1.jpeg | r/battlemaps | dense desert town (architectural) |
| map03 | qwuht4d16jmf1.jpeg | r/battlemaps | fairground / circus (mixed) |
| map04 | izdad8phfdpf1.jpeg | r/dndmaps | line-art trap illustration (NOT a battlemap) |
| map05 | nv1rwo3vbsif1.jpeg | r/dndmaps | aerial crater-city (region map) |
| map06 | yeu21juxikgf1.png | r/dndmaps | island region map (NOT a battlemap) |
| map07 | r9p4h2zsm4wg1.jpeg | r/dungeondraft | rocky ravine (organic) |
| map08 | 4tdplzso5wcf1.jpeg | r/dungeondraft | harbour / docks (mixed) |

Full URL form: `https://i.redd.it/<id>`.

## Detection results (`results/`, Auto-Wall engine, headless via `pipeline/detect.py`)

Fully-automatic run, no manual tuning, downscaled to ~2500px working edge.

| map | mode | walls | note |
|---|---|---|---|
| map02 town | edge (default) | 4305 | many real building walls found BUT long false diagonals across courtyards/water |
| map02 town | color (auto dark) | 4187 | false diagonals gone (high precision) but only catches walls of the one sampled colour (low recall) |
| map08 harbour | edge | 4624 | docks/buildings densely traced, open water correctly empty, over-fragmented |
| map01 forest | edge | 3811 | poor — edge detector latches onto foliage texture, mostly noise |
| map03 fairground | edge | 4371 | partial |

**Conclusion:** fully-automatic detection is only a rough starting point.
Edge mode = high recall / low precision (noise); single-colour mode = high
precision / low recall. Auto-Wall is designed to be **semi-automatic** (user
picks wall colours + edits the mask). Organic/region maps (map01/05/06/07) and
illustrations (map04) are poor fits by nature. See `../notes.md`.

---

# `corpus/fa/` — Forgotten Adventures battlemaps as wall ground-truth (2026-07-19)

87 **free** FA battlemaps harvested into `.dd2vtt` files (image + hand-placed
walls + doors): **20,901 wall segments, 399 doors**, coordinate-verified. This
is the largest clean real-map GT set in the project — walls are professional,
hand-authored Foundry Wall documents, not pseudo-labels.

**Provenance.** Walls come from the public repo
[Forgotten-Adventures/FA_Battlemaps](https://github.com/Forgotten-Adventures/FA_Battlemaps)
(`packs/_source/maps/*.json`, Foundry v13 scenes). Images come from FA's public
API `api.forgotten-adventures.net` (`list` → `list-files` → `get-file` returns a
signed S3 URL; **Free** maps need no auth, **Premium** returns 401 without a
Patreon `userId`).

**License / do NOT redistribute.** Map images are © Forgotten Adventures and are
**not** committed to git (`corpus/fa/` is git-ignored, like the other image
dirs). Only the harvester and these notes are tracked; the data is regenerated
on demand. Do not publish the images or the image-bearing `.dd2vtt` files.

**Reproduce** (free maps, no login):
```
python pipeline/fa_harvest.py --repo <FA_Battlemaps checkout> --out corpus/fa --access Free
```
Premium (195 more maps) needs the user's Patreon `userId` (obtained once via the
module's OAuth): add `--access Premium --userid <uuid>`.

**Coordinate handling** (see `pipeline/fa_harvest.py` docstring): walls are in
Foundry PADDED canvas pixels; image_pixel = (canvas − pad)·scale, where
pad = ceil(padding·dim/grid)·grid and scale = img_dim/scene_dim. Maps split into
BG quadrant tiles (no merged `*_BG.webp`) are reconstructed by compositing the
scene's **base** tiles only (elevation ≤ 0, no occlusion) — foreground roof/
canopy overlays are skipped so every wall stays visible in the GT view.
Alignment visually verified on tomb-of-horrors, feywild-throne, gibbet-crossing
(composite), wave-echo-cave (composite).
