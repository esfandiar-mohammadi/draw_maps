---
name: wall-detection-pipeline
description: Turn a battle-map image into few, long, editable wall segments (+ doors), exportable as UVTT or Foundry Wall documents.
when_to_use: Any work on the detection algorithm in pipeline/ — new approaches, parameter tuning, failure analysis.
tier: strong-recommended
---

# Wall detection pipeline

## Goal
From a map image, produce wall segments that (a) block vision/movement where
the map shows walls, (b) are few and long enough for a GM to edit (H4), and
(c) survive the corpus benchmark without regressions (H3).

## When NOT to use
Do not tune detection inside the Foundry module. The algorithm's source of
truth is the Python prototype in `pipeline/`; the module ports/wraps a proven
pipeline. Iterating on CV inside the browser wastes cycles.

## Preconditions
- venv: `/home/spark1admin/draw_maps/.venv` with `opencv-python`, `numpy`,
  `shapely`, `ruff` (add what you use to `pipeline/requirements.txt`).
- Test corpus + ground truth present (`verification-and-benchmarking`).
- Prior art studied before inventing: Auto-Wall
  (https://github.com/ThreeHats/auto-wall, OpenCV edge + color-clustering
  detection, UVTT export). Read its detection code once, note the ideas worth
  stealing and its failure modes in `notes.md`.

## Pipeline stages (each stage = one function, unit-testable, dumpable)

1. **Preprocess** — normalize size (cap long edge ~4096 px, remember scale),
   optional grid removal (detect periodic lines via FFT/autocorrelation before
   edge detection, or they dominate the output).
2. **Segment walls** — two interchangeable detectors behind one interface:
   (a) edge-based: grayscale → blur → Canny → dilate/close;
   (b) color-based: cluster palette (k-means), user/heuristic picks wall
   colors → binary mask. Every new detector is a HYPOTHESIS — benchmark it,
   hunt counterexample maps (CLAUDE.md working rules).
3. **Vectorize** — binary mask → contours (`cv2.findContours`) or skeleton →
   polylines.
4. **Simplify & merge (H4 lives here)** — Ramer–Douglas–Peucker
   (`shapely.simplify`) with tolerance in GRID-relative units; merge collinear
   neighbors; snap near-axis-aligned segments and nearby endpoints; drop
   segments shorter than a minimum. Targets: see benchmark metric
   `segment_economy`.
5. **Doors (later phase)** — detect door glyphs (template/shape matching or
   ML) → segments with `door: 1`.
6. **Export** — (a) UVTT JSON (`line_of_sight`, `portals`, `resolution` with
   `pixels_per_grid`; verify the spec against Auto-Wall's output before
   writing the exporter) for interop testing via Universal Battlemap Importer;
   (b) Foundry Wall-document JSON array (coordinate transform per
   `foundry-module-dev` §coordinates, H7).

## Runnable core

```bash
/home/spark1admin/draw_maps/.venv/bin/python -m pipeline.run \
    --map corpus/maps/<name>.webp --out /tmp/claude-out/<name>/ \
    --dump-stages          # writes per-stage PNGs for inspection
tools/overlay.py corpus/maps/<name>.webp /tmp/claude-out/<name>/walls.json  # then LOOK at it (H2)
```
(Create these entry points with exactly these interfaces if they don't exist yet.)

## Interpretation & pitfalls
- A detector that nails one style (e.g. crisp Dungeondraft strokes) and dies
  on photorealistic maps is still useful — as an explicitly LABELED special
  case with an auto-style-check, never as the silent default.
- Long benchmark/tuning sweeps run in tmux (`tmux new -s drawmaps`), not in
  the Claude session.
- Grid lines, floor textures, and shadows are the classic false-positive
  sources; keep one corpus map exhibiting each.

## Cross-links
`verification-and-benchmarking` (the judge), `foundry-module-dev` (the consumer).
