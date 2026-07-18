# CLAUDE.md — draw_maps: automatic wall drawing for Foundry VTT

> ⏩⏩ **RESUME HERE — Stand 2026-07-15 (nach `/clear` ZUERST lesen).**
> Der ausführliche, chronologische Verlauf steht in `notes.md` (neueste oben) —
> lies die obersten ~15 Einträge. Dieser Block ist die Kurzfassung zum Weitermachen.
>
> ### Wo wir stehen (das Projekt hat sich stark entwickelt)
> Ursprung: Add-on für Foundry VTT, das Wände auf Battlemaps automatisch zeichnet.
> Der Auto-Wall-Companion-Modul-Teil ist FERTIG & in Foundry v13 live verifiziert
> (`vendor/auto-wall-companion`, Beweise `corpus/results/test-evidence-v13-*`).
> Der Fokus liegt jetzt auf einer **eigenen ML-Wanderkennung** (Segmentierung →
> planarer Graph), weil klassisch CV/Auto-Wall auf harten Maps unbrauchbar war
> (F1 ~0.2–0.4).
>
> ### Aktueller BESTWERT (harte, ausgehaltene dd2vtt-Maps, echte GT)
> **HEAT/BYOL fine-tuned + Bildrand-Filter: F1 0.926 / P 0.89 / R 0.97.**
> Checkpoint: `vendor/heat/checkpoints/ckpts_heat_byol_full/checkpoint_best.pth`,
> Eval: `pipeline/heat_eval_uvtt.py --image_size 256`. Backbone per BYOL-SSL auf
> Domäne vortrainiert (`train_byol.py` auf 176k-Pool → `inject_byol_heat.py` →
> HEAT-Finetune). Vorheriges HEAT (ImageNet-Init) 0.908; BYOL-SSL brachte +0.018.
> Verlauf: CV 0.22 → SAM 0.39 → donjon 0.43 → Mix+clDice 0.73 → ResNet-Graph
> 0.74 → DINO-Graph 0.834 → +Randfilter 0.896 → HEAT-ft 0.908 → **HEAT/BYOL
> 0.926**. Zweitbestes (komplementär): DINO-Graph 0.896 (`wall_dino_vitg.pt`).
> DINO+JEPA-SSL SCHEITERTE (0.36, Collapse; JEPA-Rezept fragil auf kleiner
> Domäne — BYOL robust). Nächster Hebel: DINO+HEAT-Ensemble (Oracle-per-map
> ~0.94). Produkt-Plus HEAT: 49M Params, nativ wenige gerade Segmente (H4).
>
> ### Was GERADE im Hintergrund läuft (Stand 2026-07-15 nachmittags)
> 1. **HEAT-Agent**: numerische Zero-Shot-Eval von HEAT (vendor/heat, CUDA-Ops
>    gebaut, Checkpoints geladen) auf den 6 harten Maps + dd2vtt→S3D-Konverter
>    + Smoke-Train. Frage: schlägt/ergänzt HEAT (Fine-Tune) den DINO-Graphen?
> 2. **UVTT-Harvest-Agent**: corpus/real_uvtt validieren (36 GitHub-Dateien),
>    BBEG-Adventures-0€-Checkout fortsetzen, README/Lizenzen schreiben.
> donjon-Harvest GESTOPPT bei ~143,5k (genug; Cap 8000 beim Training!).
> DINO-Frage von heute Vormittag BEANTWORTET: JA, 0.834 > 0.738 → DINO ist
> das Backbone (Details notes.md).
>
> ### Nächste Schritte (Reihenfolge + WARUM)
> 1. **Objekterkennung** (der aktuelle Kern-Fehler: Brücken werden als Fassaden-
>    Verlängerung gelesen, Schornsteine als Gebäudeende). Plan in `OBJECT_MODELS.md`:
>    **Grounding DINO** (open-vocab, Prompts „bridge/chimney/water/stairs/tower") →
>    Masken → Wandgraph korrigieren (Brücke=begehbar, Schornstein→ins Gebäude
>    verschmelzen). Grounding DINO ≠ DINOv2 (anderes Modell!).
> 2. **Verschränkte Detektion↔Segmentierung** (User-Design): Objekt-Hypothese →
>    Seg trennt in Unterobjekte → bestätigt/lehnt Trennung ab (erkennt Zusammen-
>    gehörigkeit) → erneuter Versuch → wenn beide sich einig sind (inkl. Türen/
>    Fenster) → saubere Wand-Graph-Segmentierung auf den Gebäuden.
> 3. **Precision heben** (0.65): mehr realer Trainingsanteil, stärkere Knoten-/
>    Kanten-Regularisierung, Kanten-Verifikation über die Wandwahrscheinlichkeit
>    zwischen zwei Knoten.
>
> ### WARUM dieser Weg
> - **Domänen-Mix** (reale dd2vtt-Maps + donjon) war DER Durchbruch (0.43→0.73).
>   Mehr donjon allein bringt nichts (Domänenkluft Pixelart↔gemalt); der Real-
>   Anteil ist der Hebel. Reale Labels: 62 dd2vtt-Maps (`vendor/vtt-maps`, Bild+
>   Wände) + donjon-Synthetik (gleicher Seed, Standard-Stil → Wandmaske, hübscher
>   Stil → Trainingsbild) + Reddit-Pseudolabels (wo CV & SAM übereinstimmen).
> - **clDice** = Verbundenheits-Loss (lange, unverbundene→bestraft). **Footprint-
>   Labels** = gelernte, variable Wanddicke (kein fester Postprocessing-Merge).
>   **Planarer Graph** (Junction-Kanal + Skelett+DP + Kollinear-Merge) = Punkte +
>   Kanten + Dicke pro Abschnitt + Knoten-Reduktions-Reg (User-Wunsch).
> - **DINO-Fine-Tune** = stärkere vortrainierte Features testen (nur letzte 4 Layer).
>
> ### Pipeline-Dateien (`pipeline/`)
> `grid_detect.py` Raster · `grid_walls.py` CV-Grid-Detektion (+ Helfer: merge_runs,
> weld_endpoints, prune_isolated) · `sam_walls.py` SAM-Regionen→Wände ·
> `region_classifier.py`/`train_region_clf.py` (verworfen) · `uvtt.py` dd2vtt-Parser ·
> `donjon_harvest2.py` donjon-Harvester · `train_seg.py` U-Net-Training (clDice,
> grid-aug, last-8) · `train_graph.py` 2-Kanal Wand+Junction · `graph_infer.py`
> Graph-Aufbau · `graph_eval_uvtt.py`/`seg_eval_uvtt.py` Eval · `vectorize_walls.py`
> Polylinien · `build_real_tiles.py` reale+Pseudo-Kacheln · `train_dino.py` DINO ·
> `dino_features.py` DINO-Feature-Probe · `infer_seg.py` Inferenz.
>
> ### GOTCHAS (haben Zeit gekostet)
> - **pgrep/pkill Selbst-Match:** NIE `pkill -f "train_X.py"` in einem Befehl, dessen
>   eigene Zeile „train_X.py" enthält → killt den eigenen Wrapper (Exit 144) bzw.
>   Endlosschleife. Bracket-Trick `[t]rain_X` oder per PID killen.
> - **Gated (401):** DINOv3, Forgotten-Adventures-Assets → brauchen User-Token.
>   Zugänglich: DINOv2 (torch.hub), donjon, mbround18/vtt-maps.
> - **Env:** `.venv` (torch 2.13+cu130, ultralytics, segmentation-models-pytorch,
>   skimage, scikit-learn). GB10 aarch64 CUDA 13.0. Node: `~/.nvm/versions/node/v24.18.0/bin`.
>   numpy 2.0: `np.ptp(a,axis=)` statt `a.ptp()`.
> - **Forge:** Instanz auf v13, Test-Welt „wall-test" existiert; Passwort im Chat
>   geteilt → User soll rotieren.
> - **Lange Jobs:** `run_in_background:true`; Fortschritt über Modell-Dateidatum +
>   Log-`grep` prüfen (Task-tmp-Pfade sind session-spezifisch, Modelle/corpus/notes
>   sind dauerhaft).

---

This file is a step-by-step operating manual, not background reading. Follow it
literally. When it says "do X, do not ask", do X without asking. When it says
"measure", a glance at a screenshot does not count.

## Project goal

Build a **Foundry VTT add-on module** that takes a scene's battle-map image and
**automatically draws the walls** (plus doors and, later, windows/lights) as
native Wall documents, so a GM can import a map and have working vision/movement
blocking in seconds instead of tracing hundreds of segments by hand.

Verified context (2026-07-14; re-verify before relying on it):
- Foundry VTT stable is **v14** (release 14.359); v13 is still widely used.
  Target v13+v14 compatibility unless decided otherwise.
  https://foundryvtt.com/releases/
- **Prior art exists and must be studied, not reinvented:**
  [Auto-Wall](https://github.com/ThreeHats/auto-wall) — external PyQt6 desktop
  app, OpenCV edge/color detection, exports **UVTT** (Universal VTT JSON);
  its companion module: https://foundryvtt.com/packages/auto-wall-companion.
  UVTT files are imported into Foundry via "Universal Battlemap Importer".
  Our differentiator: detection **inside Foundry** (or one-click from Foundry),
  no external app round-trip.
- Official API docs: https://foundryvtt.com/api/ — the ONLY authority on the
  Foundry API (see hard rule H1).

## PRIME DIRECTIVE (user, 2026-07-14): buy before build

If Auto-Wall + Universal Battlemap Importer already do what the user wants,
USE THEM — implement nothing. Therefore:

- **Phase 0 (mandatory, before any implementation):** evaluate the existing
  toolchain end-to-end — install Auto-Wall locally (MIT license, Linux
  .deb/AppImage), run it on a small representative map set, export UVTT,
  import into the user's Forge instance via Universal Battlemap Importer,
  and judge the resulting walls in-game (H2: overlays/screenshots + numbers).
- **Decision gate:** report findings as fit/gap table. Only gaps the user
  confirms as blocking justify building anything, and then the smallest
  thing that closes the gap (e.g. a thin Foundry module wrapping Auto-Wall's
  pipeline for one-click use) — not a from-scratch rewrite.
- Everything below about building a module is CONDITIONAL on that gate.

## Open decisions (settle with the user before building the affected part)

0. **Phase-0 verdict** — does Auto-Wall meet the need as-is? (Known caveat to
   probe: it is an interactive desktop app with an export/import round-trip,
   not one-click inside Foundry; is that acceptable to the user?)
1. **Architecture (only if building)** — where does the computer vision run?
   (a) fully in-browser (JS: OpenCV.js / onnxruntime-web) — zero install, but
       heavy assets and limited CPU;
   (b) companion Python service the module calls (localhost HTTP) — full
       OpenCV/ML power, but extra install step;
   (c) hybrid: classical CV in-browser, optional ML service for hard maps.
   Prototype the detection pipeline in Python FIRST regardless (fast iteration,
   see `skills/wall-detection-pipeline.md`); port or wrap once quality is proven.
2. **Distribution** — GitHub repo + Foundry package listing (public) vs. private.
   Publishing anywhere is ask-first.

## Working rules

**Autonomy.** For multi-step technical tasks (pipeline experiments, module
builds, iterative debugging) do NOT stop after each sub-step to ask for
confirmation. Work the whole task through to done or to a hard-to-reverse
action. Give one-line progress notes on the way. "Go" / "yes" authorizes the
WHOLE task loop below, not just the next sub-step.

**Never ask permission to:** edit files, run builds/lints/tests, run the
detection pipeline on test maps, render/inspect overlays, create scratch files,
manage own background processes, initialize/commit to the LOCAL git repo,
update `notes.md`/`MEMORY.md`, fix bugs discovered during verification (fix,
verify, mention in the report).

**Ask first, always:** publishing anything (GitHub push to a public remote,
Foundry package registry, forum posts); deleting files you did not create;
anything that modifies a real Foundry user-data world outside the dedicated
test world; expanding scope beyond the request (propose it in the report
instead).

**Research.** Research every factual claim (API signatures, format specs,
version compatibility), cite the URL, and re-fetch the URL to confirm it
supports the claim before writing it down. This applies doubly to the Foundry
API: it changes between major versions and training-data memory of it is
unreliable (H1).

**Hypotheses.** Treat every detection idea ("Canny + Hough will find these
walls", "color clustering separates floor from wall") as a hypothesis to
refute: run it on a realistic, diverse map corpus and actively hunt for
counterexample maps that break it. One counterexample kills the general claim —
then check whether it still holds for a well-defined special case (e.g. "maps
with uniform dark wall strokes") and hunt counterexamples for THAT. When the
user proposes a hypothesis, your first move is also to look for
counterexamples. Record verdicts in `notes.md`.

## THE TASK LOOP — follow for EVERY change, in order, without stopping

1. **Baseline.** Before changing detection code, save the current corpus
   metrics and overlays: `tools/benchmark.sh --tag baseline` (once it exists;
   until then, copy current outputs to `/tmp/baseline_drawmaps/`).
2. **Edit.** Smallest change that fixes the problem — at the right LEVEL: a
   detection failure on one map is a pipeline/parameter bug; fix the pipeline,
   never hand-tune a single map (H6).
3. **Build & lint.** Python: run the pipeline entry point + `ruff check`.
   Module JS: the build/lint command in `module/README.md`. Never treat a run
   with errors as success.
4. **Regression check.** Re-run the corpus benchmark and diff metrics against
   baseline. Maps you did NOT intend to affect must not regress; maps you DID
   target must improve. If nothing changed, your edit was a silent no-op — find
   out why before going on (H8).
5. **Inspect.** Render wall overlays for every changed map and actually LOOK
   at them with the Read tool (H2). For module changes: load the test world,
   run the feature, screenshot, look.
6. **Record.** Add an entry at the TOP of `notes.md`: what was wrong, root
   cause, fix, metric deltas, verification scope. Reusable pitfalls go into the
   matching skill file. Commit locally with a message describing cause and fix.
7. **Report.** Outcome first, then detail (see Reporting).

## HARD RULES

- **H1 — Never trust API memory.** Before using any Foundry API (document
  schema, hook name, canvas API, manifest field), verify it against
  https://foundryvtt.com/api/ (or the foundryvtt.wiki dev guides) for the
  TARGETED core version, and record the verified fact with URL in
  `skills/foundry-module-dev.md`. A module that "looks right" from memory and
  fails on load is the expected failure mode, not bad luck.
- **H2 — Measure, don't eyeball.** Wall quality is judged by (a) overlay
  renders you actually looked at AND (b) numbers: segment count, total length,
  coverage/precision vs. hand-made ground-truth walls on the test corpus
  (`skills/verification-and-benchmarking.md`). "Looks plausible" is not a
  result.
- **H3 — Corpus, not anecdotes.** Never judge a detection change on one map.
  The test corpus spans styles (hand-drawn, Dungeondraft, photorealistic,
  gridded/gridless, dark/light). A change ships only if the corpus says net
  improvement and no targeted map regressed.
- **H4 — Walls must be editable, not pixel noise.** Output few, long, snapped
  segments a GM can adjust (simplification/merging is part of the pipeline,
  not optional polish). A wall set with thousands of 2-px segments is a
  failure even if coverage is 100% — it lags the canvas and can't be edited.
- **H5 — Never destroy user data.** The module never deletes or overwrites
  existing walls without an explicit in-UI confirmation, and every bulk
  operation must be undoable (single undo step / stored previous state).
  Development happens in a dedicated throwaway test world only.
- **H6 — Fix systemically.** A bug visible on one map/scene is a bug in the
  algorithm or its parameters. Fix it there, then re-verify the WHOLE corpus,
  not just the reported map. Per-map overrides only for genuinely map-specific
  values, and they live in explicit config, not code.
- **H7 — Coordinates are a minefield.** Image pixels ≠ canvas coordinates:
  scene padding, background offset/scale, and grid size all shift wall
  endpoints. Every coordinate transform gets a unit test with known-answer
  fixtures before it is used (`skills/foundry-module-dev.md` §coordinates).
- **H8 — Verify the EFFECT, not the absence of errors.** A change that runs
  cleanly can be a complete no-op. Prove the new logic fires: log the computed
  value once, or check that exactly the intended corpus maps changed.

## Environment

- Python venv: `/home/spark1admin/draw_maps/.venv` — create with
  `python3 -m venv .venv` at first need; system Python is PEP-668
  externally-managed, never pip-install into it.
- Long runs (corpus benchmarks, model inference) go into tmux, not the Claude
  session: `tmux new -s drawmaps`, log via `tee /tmp/drawmaps_run.log`.
- GPU: CUDA available (`cuda`) if ML models are used.
- Local git: initialize at project start (pre-authorized). Remote publishing:
  ask first.
- Foundry test instance: document install path, launch command, and test-world
  name in `notes.md` as soon as it exists; never point the module at a real
  world.

## FILE MAP (planned layout — keep current as the project grows)

| Path | Role |
|---|---|
| `CLAUDE.md` | this operating manual |
| `skills/` | runbooks; `skills/README.md` is the menu — scan it first |
| `pipeline/` | Python detection prototype (the algorithm source of truth) |
| `module/` | the Foundry module (module.json, esmodules, styles, lang) |
| `corpus/` | test maps + ground-truth walls (`corpus/README.md` lists provenance/licenses) |
| `tools/` | benchmark.sh, overlay renderer, metrics, UVTT export/import helpers |
| `notes.md` | session log, newest on top — read the top 2–3 entries when starting work |
| `MEMORY.md` | intermediate state snapshots at every major step (dpscans convention) |

## Reporting

Lead with the outcome ("wall detection on the corpus: precision X→Y, overlays
verified on maps A–C, committed as <hash>"), then root cause, then verification
scope, then anything you noticed but did not do (as proposals, not questions).
Report failures just as plainly: if a step failed or was skipped, say so —
never present unverified work as done.
