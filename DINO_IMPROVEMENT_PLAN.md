# DINO pipeline improvement plan — target: FA-in-scope graph-F1 0.728 → 0.9

Status: **PROPOSED, not executed** (user asked for a plan first). Written 2026-07-21,
based on 4 web-research sweeps (dense heads / losses / vectorization / data) plus
local per-map evidence. All external claims carry URLs; magnitudes are from analog
domains (roads, vessels, aerial buildings) — treat as directional, verify on our
in-scope-32 benchmark (H2/H3).

## 1. Where the 0.172 gap actually is (local evidence)

Per-map MS eval of `wall_dino_fa_inscope.pt` (`corpus/results/eval_inscope_ms.log`,
n=32): **F1 0.728, P=0.819, R=0.670**.

- **Recall is THE gap** (P−R = +0.15), uniformly across maps — not a tail problem.
  Only 1 map <0.5 (decrepit-estate-attic 0.46). Caves 0.747 vs buildings 0.721 —
  nearly even. A broad recall lift is needed, not per-map fixes.
- **Mask Dice plateaus ~0.63–0.67** while graph-F1 is 0.728 — both the mask AND the
  hand-crafted vectorization (skeletonize→DP→snap→collinear-merge) are in play.
  Seg-era measurement had mask-UB 0.559 vs graph 0.507 (~9% relative loss in
  vectorization); the DINO-era number is unmeasured → Phase-0 diagnostic.
- **Routing ceiling is currently thin**: oracle max(DINO-MS, HEAT-ep48) = **0.759**
  (+0.031); naive type-routing (caves→DINO, bldg→HEAT) is WORSE (0.692) — winner
  does not follow the cave/building split. Revisit once HEAT converges.
- Tversky flag convention **verified correct**: SMP puts β on the FN term
  (`soft_tversky_score`: `alpha*fp + beta*fn`), so `--tversky_beta 0.7` is
  recall-favoring as intended. Ready to run.

**Strategy that falls out: push RECALL in the mask, restore PRECISION in the graph.**
Recall-shaped losses + resolution give the mask more true wall pixels (accepting some
FP); a learned/optimization edge-verification stage then prunes hallucinated edges at
the graph level, where verification is easy (integrate wall-prob along each edge).

## 2. The plan (phased; each phase gated by in-scope-32 eval, single + MS)

### Phase 0 — Diagnostics (hours, CPU-heavy, can run during HEAT training)

| # | What | Why / method |
|---|---|---|
| 0.1 | **Mask-UB vs graph-F1** on in-scope-32: score the raw DINO wall mask against rasterized GT (skeleton-tolerance F1), compare to achieved graph-F1 | Splits the 0.172 gap into "mask problem" vs "vectorization problem" → sets Phase-1/2 budget split |
| 0.2 | **Recall-miss taxonomy**: overlays of the 6 worst-R maps; classify misses (thin walls? low contrast? style? wall-type e.g. palisades/fences?) | Picks the right augmentation lever; H2 look-at-it discipline |
| 0.3 | ~~Tversky convention check~~ | DONE (correct, see §1) |

### Phase 1 — Cheap recall + graph cleanup (days; small GPU windows, fits beside Gemma)

| # | Lever | Effort | Evidence | Expected |
|---|---|---|---|---|
| 1.1 | **Tversky retrain** `--tversky_beta 0.7` (flag exists, unmeasured). Optionally Focal-Tversky γ=4/3 as variant | S | Salehi 2017 (https://arxiv.org/pdf/1706.05721) — motivation is verbatim our P>R mode; γ rec. from https://arxiv.org/abs/1810.07842 | few ×0.01 |
| 1.2 | **Skeleton Recall Loss** replaces `0.4·soft_cldice` | S–M | ECCV 2024, https://arxiv.org/abs/2404.03010, code Apache-2.0 https://github.com/MIC-DKFZ/Skeleton-Recall. Recall-only on GT centerline = exactly our failure; +8% time/+2% VRAM vs clDice's +88%/+52% → also frees VRAM under the Gemma squeeze | connectivity (−26% β₀ on Roads), small F1 |
| 1.3 | **4-way flip TTA** added to MS inference (avoid rotation TTA) | S | crack-seg verified +2.0 F1, driven by +4.2 recall: https://arxiv.org/html/2409.02866v1 | +0.01–0.02 |
| 1.4 | **MRF/graph-cut edge pruning** on the existing graph: unary = wall-prob integral along edge + border-box penalty; pairwise = junction-degree consistency; solve via graph cuts (pygco) | S (1–2 d) | No packaged tool exists (verified); Floor-SP objective as template (https://github.com/woodfrog/floor-sp). Attacks graph-level FP incl. the border-box leak; composes with HEAT output too | the "floor" any learned vectorizer must beat |

Run 1.1+1.2 as ONE retrain (both are loss swaps; watch precision — 1.4 is the safety
net). Gate: in-scope-32 ≥ 0.75 expected before Phase 2.

### Phase 2 — Resolution, head, hard examples (1–2 weeks)

| # | Lever | Effort | Evidence | Expected |
|---|---|---|---|---|
| 2.1 | **Input 252→518** fine-tune (token grid 18²→37², same stride-14). LoRA instead of last-4 to fit VRAM (fewer optimizer states); bs 1–2 + grad-ckpt | M | 518 = documented ViT-g high-res operating point (https://deepwiki.com/facebookresearch/dinov2/2-model-architecture); LoRA ≈ full-FT on small dense sets (https://arxiv.org/pdf/2603.28297) | the single most direct thin-wall lever on current backbone |
| 2.2 | **4-layer `get_intermediate_layers` fusion** (+optional DPT-style head) | S–M | DINOv2 paper: +0.057 IoU on ViT-L, diminishing with size (https://arxiv.org/html/2304.07193v2) | small; nearly free with 2.1 |
| 2.3 | **Pixel-OHEM** (top-k hard-pixel loss, ~30 lines) + **FDA** amplitude-swap on donjon crops toward painted spectra (~20 lines) + deep supervision at 2–3 scales | S each | OHEM: https://mmsegmentation.readthedocs.io/en/latest/advanced_guides/training_tricks.html; FDA: https://arxiv.org/abs/2004.05498 (exactly our synthetic→painted gap) | attacks texture/furniture FP + donjon domain gap |
| 2.4 | **Learned edge-verification head** (HAWP-crib): LoI-pool DINO features/wall-prob along every proposed edge → small MLP accept/reject. **Labels fall out of our graph-F1 matcher for free** (matched=pos). Upgrades 1.4 | M | HAWPv2 MIT https://github.com/cherubicXN/hawp; 275 tiles → thousands of edge samples | composes with DINO AND HEAT paths |

Gate: ≥ ~0.80 before committing to Phase-3 spend.

### Phase 3 — Structural (bigger jumps, need user decisions/resources)

| # | Lever | Effort | Blocker/risk | Evidence |
|---|---|---|---|---|
| 3.1 | **DINOv3 ViT-L backbone swap** — smaller than our ViT-g (0.3B vs 1.1B) AND better on dense tasks (gram anchoring fixes dense-feature degradation; 63.0 mIoU ADE20k frozen; ViT-L ≈ 7B-teacher) | M | **Gated**: user must accept Meta license on HF (https://ai.meta.com/resources/models-and-libraries/dinov3-license/). Freed VRAM enables 518+ and stock upsamplers (LoftUp ≤ViT-B, AnyUp) | https://arxiv.org/html/2508.10104v1 |
| 3.2 | **UniMatch V2 semi-supervised** on the 176k unlabeled pool — already DINOv2-based. MUST adapt for thin structures: low/adaptive wall-class threshold + connectivity-aware pseudo-label refinement, else it entrenches the recall deficit | M | pseudo-label pitfalls for thin structures documented (https://arxiv.org/pdf/2309.15625) | VOC 1/16 labels: 45.1→86.3 mIoU (https://arxiv.org/abs/2410.10777, https://github.com/LiheYoung/UniMatch-V2) |
| 3.3 | **ControlNet synthetic data** (FreeMask recipe): our wall masks → `mlsd`/`seg` ControlNet + battlemap style LoRA → style-diverse maps with pixel-perfect labels; over-generate the failing styles (hard-mask re-sampling). Supersedes the inconclusive copy-paste attempt | S–M infer / M train | VRAM ok (SD1.5 + 8-bit Adam ≈16GB, https://huggingface.co/docs/diffusers/training/controlnet); **check Civitai LoRA licenses** (e.g. https://civitai.com/models/2164519) | FreeMask +3.3 mIoU joint (https://arxiv.org/abs/2310.15160); mlsd ControlNet = literally straight-line conditioning (https://huggingface.co/lllyasviel/control_v11p_sd15_mlsd) |
| 3.4 | **CAGE as HEAT successor** for the routing partner: edge-native output (open segments, no closed-room prior), density-map input ≈ our mask, +9.2/+11.0 corner/angle F1 over HEAT on S3D | M | license SPDX NOASSERTION (verify); deform-attn CUDA on aarch64 (we've patched this class); 211M params under Gemma squeeze | https://github.com/ee-Liu/CAGE, https://arxiv.org/abs/2509.15459 |
| 3.5 | **ScaleLSD zero-shot probe** (hours, MIT, domain-agnostic self-supervised LSD) + optional LINEA-S fine-tune `[RGB, wall_prob]` for the buildings route (12-epoch recipe, Apache-2.0) | S / S–M | wireframe models are straight-line-only → buildings subset; caves stay on DINO+skeleton | https://github.com/ant-research/scalelsd, https://github.com/SebastianJanampa/LINEA |

### Cross-cutting — per-map routing DINO×HEAT
Hold until HEAT-in-scope converges (training running). Today's oracle is only 0.759;
a learned gate is worth building only if the converged oracle reaches ~0.85. The
edge-verification stage (1.4/2.4) is the better first merger: it can score edges
from BOTH models in one graph (soft ensemble at graph level, not mask level).

## 3. Explicitly deprioritized (with reasons — don't re-litigate)

- **Boundary/Hausdorff/ABL losses** — improve boundary localization, not thin-structure recall; wrong error mode.
- **Betti matching / DconnNet** — cost (persistent homology) resp. full architecture change.
- **Ensemble-then-distill** — our own oracle (+0.031 at ep48) caps the upside below literature's +1–3 mIoU.
- **Active learning for new labels** — evidence says ~random once SSL+strong aug are in play (https://arxiv.org/abs/1912.05361).
- **RobustNet/SHADE style-debias** — CNN-centric retrofits, awkward on ViT.
- **Rotation TTA** — reported to hurt; flips only.
- **Type-based routing** (caves→DINO, bldg→HEAT) — measured WORSE (0.692) than DINO alone.
- **Learned feature upsamplers on ViT-g** — no pretrained FeatUp/LoftUp for ViT-g exists (verified via repo issues); only viable after a ViT-B/L move.

## 4. Execution constraints & order of operations

- **GPU**: shared with Gemma (7–19GB CUDA-free, OOM spikes). All trainings:
  `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`, launch-retry loop, setsid.
  HEAT-in-scope training occupies the GPU (~10 min/ep, cap 250) — Phase-1 retrains
  are short but must interleave or wait for the HEAT stop decision.
- **Sequencing**: Phase 0 now (CPU-safe) → Phase 1 as one combined retrain + two
  inference-side changes → measure → Phase 2 → measure → Phase-3 picks by gap
  remaining and user decisions (DINOv3 license = user action; Civitai licenses).
- **Measurement discipline**: every step evaluated on in-scope-32 (single + MS),
  per-map; no step ships on mean alone if targeted maps regressed (H3). Compute
  in-scope mean manually against `corpus/fa_test_inscope.txt` (no CLI flag).
- **Honesty about magnitude**: no researched lever showed a single 0.73→0.9 jump in
  any adjacent domain. The plan reaches 0.9 only if several levers stack:
  Phase 1 ≈ 0.75–0.78 → Phase 2 ≈ 0.80–0.84 → Phase 3 closes the rest (DINOv3 +
  SSL + synthetic data are the big three). If Phase 1+2 underdeliver, revisit with
  the Phase-0 diagnostics before spending Phase-3 effort.

## 5. User decisions needed before the affected steps

1. **DINOv3 license** (3.1): accept Meta's gated license on HF + provide token.
2. **Civitai LoRA licensing** (3.3): ok to use community battlemap LoRAs for
   synthetic training data? (licenses unverified; alternative: fine-tune our own
   LoRA on the 267-map FA corpus we already have).
3. **Budget call after each phase gate**: continue vs stop-and-ship.
