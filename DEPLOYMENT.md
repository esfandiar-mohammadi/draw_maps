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
| DINOv2 ViT-g teacher (multi-scale) | 1.1 B | **0.786** (Phase-1) | ~seconds, GPU-class |
| **ConvNeXt-Tiny student — DEFAULT (fp32 ONNX, single-scale, wall_thr 0.5)** | **32 M** | **0.765** | **~0.84 s** (this host) |
| MobileNetV3-L student — fallback (fp32 ONNX, wall_thr 0.4) | 6.7 M | 0.741 | 0.65 s |
| MobileNetV3-L ncnn fp16 (Vulkan-capable) | 6.7 M | 0.722 | ~0.6 s CPU / Vulkan on RX 6600 |
| EfficientNet-B4 student (rejected) | 20 M | 0.740 | — |
| student INT8 ONNX | 6.7 M | 0.380 ✗ | 0.32 s |

**ConvNeXt-Tiny is the shipped default** (graph-F1 0.765 @wall_thr 0.5): +0.024
over MobileNetV3 and only 0.021 under the 1.1 B teacher. Capacity — not the
teacher — was the ceiling; EfficientNet-B4 at 20 M matched MobileNetV3, so it is
the ConvNeXt *architecture* (LayerNorm + 7×7 depthwise + GELU), not raw params.
Single-scale matches multi-scale, so deployment uses single-scale 1024. On the
target Ryzen 3600 (no VNNI) expect roughly ~2–2.5 s/map — fine for a one-shot
import. **INT8 is NOT usable** (per-channel QDQ collapses the student, 0.72→0.38)
— ship fp32.

The **MobileNetV3-L student (0.741, 26 MB)** stays as the documented fallback: it
is smaller/faster and is the **only** model with a working ncnn/Vulkan path (see
§1). ConvNeXt-Tiny does **not** convert to ncnn — pnnx miscompiles its decoder
(a plain 3×3 conv emits `inf`; NaN output, fp16 *and* fp32 alike), so the
ROCm-free GPU path is MobileNetV3-only.

## 1. Run the companion service (target machine: Ryzen 3600 / RX 6600)

Pure CPU via onnxruntime — **no ROCm/CUDA needed** (the RX 6600's gfx1032 is
ROCm-unsupported anyway; see DISTILL_PLAN.md §2). The default model is
ConvNeXt-Tiny (wall_thr baked to 0.5):

```bash
bash tools/run_wall_service.sh 8177
# or explicitly:
.venv/bin/python pipeline/wall_service.py --port 8177
# GET  http://localhost:8177/health   -> {..., "model":"wall_student_convnext_tiny.onnx", "wall_thr":0.5}
# POST http://localhost:8177/detect   body = image bytes -> {walls:[[x0,y0,x1,y1],...]}
```

Faster/smaller fallback — MobileNetV3-L (remember `--wall_thr 0.4`):

```bash
.venv/bin/python pipeline/wall_service.py \
    --model pipeline/models/wall_student_mbv3.onnx --wall_thr 0.4 --port 8177
```

Optional GPU path (ROCm-free), **MobileNetV3 only** — the ConvNeXt does not
convert to ncnn. The MobileNetV3 ONNX also ships as ncnn
(`wall_student_mbv3.ncnn.param`/`.bin`, fp16) with an ncnn backend for the
RX 6600 via Vulkan/RADV:

```bash
.venv/bin/python pipeline/wall_service.py --backend ncnn --vulkan \
    --model pipeline/models/wall_student_mbv3.ncnn.param --wall_thr 0.4 --port 8177
```

MobileNetV3 ncnn quality is verified identical to its ONNX (graph-F1 0.722 vs
0.721; wall-mask IoU 0.976). Vulkan latency must be measured on the target (dev
box has no Vulkan GPU). The ConvNeXt CPU path already meets the one-shot budget,
so Vulkan is opt-in and trades 0.765→0.722 for GPU speed. Full steps +
conversion (pnnx) in INSTALL.md §C.6; standalone eval `pipeline/ncnn_eval.py`.

## 2. Install the Foundry module

`install.sh` installs the module automatically on a box that runs Foundry
locally (finds the Foundry data dir; see INSTALL.md §C.2). To do it by hand:
`vendor/auto-wall-companion/module.zip` (id `auto-wall-companion-ml` v2.1.0;
rebuild: `npm run build && cd dist && zip -r ../module.zip .`) → extract into
`<FoundryData>/Data/modules/auto-wall-companion-ml/` (the `-ml` folder name is
required — the plain `auto-wall-companion` id collides with the archived
upstream), then enable it in the world.

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

The student is teacher-agnostic. To re-train the ConvNeXt-Tiny default (or after
any teacher improvement, DINO_IMPROVEMENT_PLAN.md):

```bash
.venv/bin/python pipeline/train_student.py --encoder tu-convnext_tiny --pseudo corpus/distill_pl_p1 \
    --out pipeline/models/wall_student_tu_convnext_tiny.pt
.venv/bin/python pipeline/export_student_onnx.py \
    --ckpt pipeline/models/wall_student_tu_convnext_tiny.pt \
    --encoder tu-convnext_tiny --out pipeline/models/wall_student_convnext_tiny.onnx
```

(MobileNetV3 fallback: `--encoder timm-mobilenetv3_large_100`, default ckpt/out
paths.) Model artifacts (`pipeline/models/*.onnx|*.pt`, `corpus/distill_pl*/`)
are git-ignored (size); regenerate as above. graph-F1 check any time:
`STUDENT_EVAL_DEV=cpu .venv/bin/python pipeline/graph_eval_student.py
--ckpt pipeline/models/wall_student_convnext_tiny.onnx --encoder tu-convnext_tiny
--scales 1024 --wall_thr 0.5`.
