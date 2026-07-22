# Deployment: automatic wall drawing in Foundry VTT

End-to-end system (built 2026-07-22): a battle-map image goes in, native Foundry
Wall documents come out, via a distilled CNN running on ordinary hardware.

```
Foundry scene ──"Detect Walls (ML)" button──▶ local companion service ──▶ walls
 (auto-wall-companion module)                  (pipeline/wall_service.py)
```

## Quality (in-scope-32 graph-F1, same protocol as the teacher)

Numbers below use the **frame-aware `drop_border_edges`** vectorizer (default
since the Phase-0 diagnostic showed the old blanket border filter discarded real
perimeter walls, costing ~0.02 student / ~0.04 teacher graph-F1 for free). The
old-blanket-filter numbers are in parentheses.

| model | params | graph-F1 | CPU latency @1024² |
|---|---|---|---|
| DINOv2 ViT-g teacher (multi-scale) | 1.1 B | **0.768** (was 0.728) | ~seconds, GPU-class |
| **distilled student (fp32 ONNX, single-scale)** | **6.7 M** | **0.741** (was 0.721) | **0.65 s** (this host) |
| student ncnn fp16 (single-scale) | 6.7 M | 0.742 | ~0.6 s CPU / Vulkan on RX 6600 |
| student INT8 ONNX | 6.7 M | 0.380 ✗ | 0.32 s |

The distilled student is **~0.027 below the teacher at ~180× fewer parameters**,
and single-scale matches multi-scale — so deployment uses single-scale 1024.
**INT8 is NOT usable** (per-channel QDQ still collapses MobileNetV3's
hardswish/hardsigmoid activations, 0.72→0.38) — ship fp32. On the target
Ryzen 3600 (no VNNI) expect roughly ~1.3 s/map single-scale; fine for a
one-shot import.

## 1. Run the companion service (target machine: Ryzen 3600 / RX 6600)

Pure CPU via onnxruntime — **no ROCm/CUDA needed** (the RX 6600's gfx1032 is
ROCm-unsupported anyway; see DISTILL_PLAN.md §2):

```bash
.venv/bin/python pipeline/wall_service.py \
    --model pipeline/models/wall_student_mbv3.onnx --port 8177
# GET  http://localhost:8177/health
# POST http://localhost:8177/detect   body = image bytes -> {walls:[[x0,y0,x1,y1],...]}
```

Optional faster GPU path (ROCm-free): the ONNX is also shipped as ncnn
(`wall_student_mbv3.ncnn.param`/`.bin`, fp16) and the service has an ncnn backend
for the RX 6600 via Vulkan/RADV:

```bash
.venv/bin/python pipeline/wall_service.py --backend ncnn --vulkan \
    --model pipeline/models/wall_student_mbv3.ncnn.param --port 8177
```

Quality is verified identical (ncnn graph-F1 0.722 vs ONNX 0.721; wall-mask IoU
0.976). Vulkan latency must be measured on the target (dev box has no Vulkan
GPU). The CPU path already meets the budget, so this is opt-in. Full steps +
conversion (pnnx) in INSTALL.md §C.6; standalone eval `pipeline/ncnn_eval.py`.

## 2. Install the Foundry module

`vendor/auto-wall-companion/module.zip` (rebuild: `npm run build && cd dist &&
zip -r ../module.zip .`). Install into `Data/modules/auto-wall-companion/` or via
the host's module importer, then enable it in the world.

- A new **"Detect Walls (ML)"** button appears in the Walls scene controls.
- Set the service URL in module settings (default `http://localhost:8177`).
  A browser on `https://…forge-vtt.com` may call `http://localhost` — localhost
  is a secure context exception.
- The button fetches the scene background, POSTs it to the service, transforms
  image-pixel segments to canvas coordinates (accounting for scene padding and
  background scale, unit-tested), and creates walls in batches of 100.
- **Existing walls are never touched.** The last detection is undoable from the
  same dialog (single step, H5).

## 3. Retrain / re-distill

The student is teacher-agnostic. After any teacher improvement
(DINO_IMPROVEMENT_PLAN.md):

```bash
setsid bash tools/distill_sprint.sh      # pseudo-label -> train -> eval (~40 min)
.venv/bin/python pipeline/export_student_onnx.py \
    --ckpt pipeline/models/wall_student_mbv3.pt --out pipeline/models/wall_student_mbv3.onnx
```

Model artifacts (`pipeline/models/*.onnx|*.pt`, `corpus/distill_pl/`) are
git-ignored (size); regenerate with the sprint. graph-F1 check any time:
`STUDENT_EVAL_DEV=cpu .venv/bin/python pipeline/graph_eval_student.py
--ckpt pipeline/models/wall_student_mbv3.onnx --scales 1024`.
