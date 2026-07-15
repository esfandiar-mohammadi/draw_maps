---
name: verification-and-benchmarking
description: Prove a detection or module change is an improvement — corpus, ground truth, metrics, overlays, regression protocol.
when_to_use: Task-loop steps 1, 4, 5 of every change; when adding corpus maps; when a quality claim needs numbers.
tier: any
---

# Verification & benchmarking

## Goal
Every quality claim ("detection improved", "doors work now") is backed by
corpus metrics AND inspected overlays — never by a single anecdote (H2, H3).

## The corpus (`corpus/`)
- ≥2 maps per style bucket: hand-drawn, Dungeondraft/dungeon-tool export,
  photorealistic/painted, gridded, gridless, dark-themed, light-themed —
  plus every counterexample map that ever broke a detector (they are the
  most valuable entries; add them the day they are found).
- `corpus/README.md` records provenance and license of every map. Only maps
  we may store and (if the repo goes public) redistribute — otherwise store
  a download URL + hash instead of the file.
- Ground truth: hand-traced walls per map in `corpus/truth/<name>.json`
  (same JSON schema as the pipeline output). Tracing ground truth by hand in
  Foundry and exporting it is the fastest route — it is ALSO how you learn
  what a GM-quality wall set looks like.

## Metrics (computed by `tools/metrics.py`; numbers from code, not prose)
- **Coverage (recall):** fraction of ground-truth wall length within
  tolerance (default: 0.25 grid squares) of a detected wall.
- **Precision:** fraction of detected wall length within tolerance of ground
  truth (punishes hallucinated walls from grids/textures/shadows).
- **Segment economy (H4):** detected segment count / ground-truth segment
  count. Target ≤ 2.0; >5 is a fail regardless of coverage.
- Report per map + corpus mean; store runs as CSV under `results/` tagged
  with git hash.

## Regression protocol (task-loop steps 1 and 4)
```bash
tools/benchmark.sh --tag baseline     # BEFORE the change
# ... edit ...
tools/benchmark.sh --tag <change>     # AFTER
tools/compare_runs.py results/baseline.csv results/<change>.csv
```
- Untargeted maps must not regress beyond noise; targeted maps must improve.
- No diff at all ⇒ silent no-op (H8): find out why before continuing.
- (Create these tools with exactly these interfaces at first need.)

## Overlay inspection (H2 — mandatory, numbers alone don't count either)
Render map + detected walls (red) + ground truth (green) + doors (blue) at
readable resolution, one PNG per changed map, and actually LOOK at each with
the Read tool. Check specifically: hallucinated walls on grid lines/shadows,
gaps at room corners (vision leaks!), door placement, segment fragmentation.

## Module-side verification
A pipeline that is correct in Python can still fail in Foundry (coordinate
transform, H7). Round-trip test: run pipeline → import into test world →
`canvas.scene.walls.size` matches → screenshot with walls layer visible →
compare against the overlay PNG. Corner vision leaks are only visible with a
token placed in the scene — place one and toggle its vision.

## Cross-links
`wall-detection-pipeline`, `foundry-module-dev`.
