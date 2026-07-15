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
