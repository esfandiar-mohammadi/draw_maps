---
name: foundry-module-dev
description: Build, load, and debug the Foundry VTT module — manifest, hooks, Wall documents, coordinate transforms.
when_to_use: Any work inside module/ or any code that talks to the Foundry API.
tier: strong-recommended
---

# Foundry VTT module development

## Goal
Module code that loads cleanly in the targeted Foundry versions (v13 + v14),
creates correct Wall documents, and never touches a real user world.

## Verified facts (source + date; re-verify per H1 before first use in code)

From https://foundryvtt.com/article/module-development/ (verified 2026-07-14):
- Modules live in `{userData}/Data/modules/<id>/`; the folder MUST match the
  manifest `id` exactly. Minimum content: `module.json`.
- Required manifest fields: `id` (lower-case, hyphens not underscores),
  `title`, `description`, `version`.
- JS is loaded via `esmodules` (preferred, ES6 modules) or `scripts` (legacy).
- Compatibility: `"compatibility": {"minimum": ..., "verified": ..., "maximum": ...}`.
- Lifecycle: `Hooks.on("init", ...)` during initialization,
  `Hooks.on("ready", ...)` once core data is available.

Still UNVERIFIED (memory only — verify at https://foundryvtt.com/api/ for the
targeted version BEFORE first use, then move up into the verified list with URL):
- Wall document schema: `c: [x0, y0, x1, y1]` (canvas pixels); sense fields
  `move`, `sight`, `light`, `sound` (`CONST.WALL_SENSE_TYPES`: NONE=0,
  LIMITED=10, NORMAL=20, …); `door` (0 none / 1 door / 2 secret), `ds` (door
  state), `dir` (direction).
- Bulk creation: `scene.createEmbeddedDocuments("Wall", wallDataArray)` —
  batch ALL walls into one call (one undo step, H5; one render, performance).
- Scene geometry: `scene.dimensions` (incl. `sceneX`, `sceneY`, `sceneWidth`,
  `sceneHeight`), `scene.background.src`, padding.

## Procedure — dev loop

1. Develop in `module/` in this repo; symlink it into the local test
   instance's `Data/modules/` (never copy — you WILL edit the wrong copy).
2. Dedicated throwaway test world only (H5). Document instance path, launch
   command, and world name at the top of `notes.md`.
3. After every change: reload Foundry (F5), open the browser console, and
   treat any red error OR any yellow deprecation warning from our module as a
   build failure.
4. Verify the EFFECT (H8): after running wall creation, count walls
   (`canvas.scene.walls.size` in the console) and compare to the expected
   number from the pipeline output — not just "no errors".
5. Screenshot the scene with walls visible and LOOK at it (H2).
6. The Forge instance (forge-vtt.com) is the user's hosted staging
   environment — deploy there only when asked, via manifest-URL install;
   credentials come from the user in-session and are never stored in the repo.

## Coordinates (H7 — every transform gets a known-answer unit test)

Image pixel → canvas coordinate is NOT identity:
- Scene padding shifts the background: image (0,0) maps to
  (`dimensions.sceneX`, `dimensions.sceneY`).
- If the background is scaled (scene dimensions ≠ image dimensions), apply
  the scale factor `sceneWidth / imageWidth` per axis.
- UVTT files use GRID units (`pixels_per_grid`), not pixels — convert
  explicitly and test with a fixture map whose wall positions are known.

## Pitfalls
- Manifest `id` ≠ folder name → module silently absent from the list.
- Testing only on one core generation while declaring compatibility for two:
  every release must be smoke-tested on BOTH v13 and v14.
- Creating walls one-by-one → hundreds of undo steps and re-renders; always
  batch (see above).

## Cross-links
`wall-detection-pipeline` (produces the wall data), 
`verification-and-benchmarking` (proves it is correct).
