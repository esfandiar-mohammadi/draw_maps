# Skills catalog — draw_maps

Skills are markdown runbooks the agent loads on demand (see `writing-skills.md`
for the format). This README is the **menu**: scan it to find the right skill
for a task. Status: ✅ written · 🟡 planned (write with `writing-skills.md`
when first needed).

Each skill has YAML front matter (`name`, `description`, `when_to_use`,
`tier`). Weak local models follow skills literally; strong models may treat
them as reference — but the HARD RULES in `../CLAUDE.md` bind everyone.

## Core / governance
- ✅ `writing-skills` — author and improve skills (the meta-skill).

## Foundry VTT
- ✅ `foundry-module-dev` — module anatomy, manifest, hooks, Wall document
  API, the coordinate-transform minefield, dev loop against a test world.
- 🟡 `foundry-release` — packaging, manifest+download URLs, version bump
  protocol, Forge deployment. Write when the module first leaves this machine.

## Detection
- ✅ `wall-detection-pipeline` — the CV runbook: preprocess → segment →
  vectorize → simplify → doors → export (UVTT / Wall documents).
- 🟡 `ml-wall-detection` — segmentation-model track (training data, ONNX
  export, in-browser inference). Write when classical CV hits its ceiling.

## Quality
- ✅ `verification-and-benchmarking` — test-map corpus, ground truth, metrics
  (precision/coverage/segment economy), overlay rendering, regression protocol.
