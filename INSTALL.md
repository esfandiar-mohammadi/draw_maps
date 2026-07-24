# Installation guide — Auto Wall Companion (ML)

Automatic wall drawing for **Foundry VTT**. You import a battle map, click one
button, and the walls are drawn as native Foundry `Wall` documents — working
vision and movement blocking in seconds instead of tracing by hand.

The system has **two parts** that you install separately:

```
 ┌─────────────────────────┐        HTTP         ┌──────────────────────────┐
 │  Foundry VTT             │  POST scene image   │  companion service       │
 │  "Detect Walls (ML)"     │ ──────────────────▶ │  (Python, runs on YOUR   │
 │  button (this module)    │ ◀────────────────── │   machine, CPU-only)     │
 └─────────────────────────┘     walls JSON       └──────────────────────────┘
        in the browser                                  32 M-param CNN
```

- **Part A — the companion service**: a small Python HTTP server that runs the
  wall-detection model *on your own computer*. Nothing is sent to the internet.
- **Part B — the Foundry module**: adds the "Detect Walls (ML)" button and talks
  to the service on `localhost`.

You need **both**. Install the service first (Part A), then the module (Part B).

> **Why local?** The model runs on your CPU in ~1 s per map on a modern desktop
> (~2–2.5 s on the target Ryzen 3600). Keeping it local means your maps never
> leave your machine, and there is no per-map API cost.

---

## 0. Prerequisites

| Component | Requirement |
|---|---|
| **Foundry VTT** | v12, v13, or v14 (verified on v13/v14) |
| **Python** | 3.10+ (3.12 tested) — for the companion service |
| **OS** | Linux, macOS, or Windows. Service is pure CPU — **no GPU, no CUDA, no ROCm required** |
| **RAM** | ~1 GB free while the service runs (ConvNeXt: measured peak ~750 MB at 1024²; MobileNetV3 fallback needs less) |
| **Node.js** | 18+ — **only** if you build the module from source (Part B, method 3) |

The service and the Foundry client must be able to reach each other over HTTP.
The common case (Foundry running on the same machine, in your browser at
`localhost`) works out of the box. Remote/hosted Foundry (e.g. The Forge) needs
one extra step — see [§B.4 Remote / hosted Foundry](#b4-remote--hosted-foundry).

---

## Part A — Install the companion service

### A.0 Get the code onto the box

The code lives in the **`draw_maps`** repository. Pick whichever transfer fits:

- **If the repo is published to a git host** (GitHub, a private server, …):
  ```bash
  git clone <this-repo-url> draw_maps && cd draw_maps
  ```
- **Copy the working tree directly** (no remote needed — e.g. from the dev box;
  `install.sh` locates its own repo root wherever you drop it, and the target
  needs no `git` at all):
  ```bash
  rsync -av --exclude .venv --exclude .install_state \
        --exclude node_modules --exclude corpus \
        <devbox>:/path/to/draw_maps/  ~/draw_maps/
  ```
- **Offline single file** (`git bundle`, keeps history):
  ```bash
  # on the source machine:
  git -C /path/to/draw_maps bundle create draw_maps.bundle --all
  # carry draw_maps.bundle to the box, then:
  git clone draw_maps.bundle draw_maps && cd draw_maps
  ```

Only the tracked repo files need to travel (a few MB) — plus the model below.
`.venv/`, `corpus/`, and `node_modules/` are regenerated or unneeded on the target.

### A.1 Get the model

You need the trained model file **`pipeline/models/wall_student_convnext_tiny.onnx`**
(122 MB, fp32) — the default ConvNeXt-Tiny student (graph-F1 0.765 @wall_thr 0.5).
It is *not* in git (too large for the repo). Obtain it one of two ways:

1. **Download** `wall_student_convnext_tiny.onnx` from the project's
   release/assets page and drop it into `pipeline/models/`, **or**
2. **Regenerate it** from the teacher pseudo-labels (needs a CUDA GPU):
   ```bash
   .venv/bin/python pipeline/train_student.py --encoder tu-convnext_tiny --pseudo corpus/distill_pl_p1 \
    --out pipeline/models/wall_student_tu_convnext_tiny.pt
   .venv/bin/python pipeline/export_student_onnx.py \
       --ckpt pipeline/models/wall_student_tu_convnext_tiny.pt \
       --encoder tu-convnext_tiny \
       --out  pipeline/models/wall_student_convnext_tiny.onnx
   ```

Verify it is there:

```bash
ls -lh pipeline/models/wall_student_convnext_tiny.onnx   # ~122 MB
```

> **Smaller/faster fallback:** the MobileNetV3-L student
> (`wall_student_mbv3.onnx`, 26 MB, graph-F1 0.741 **@wall_thr 0.4**) is also
> available and is the only model with an ncnn/Vulkan GPU path (§C.6). If you use
> it, pass `--model …mbv3.onnx --wall_thr 0.4`.

### A.2 Create the Python environment

```bash
python3 -m venv .venv
.venv/bin/pip install -r pipeline/requirements-service.txt
```

This installs only what the service needs (`onnxruntime`, `opencv`, `numpy`,
`scikit-image`) — CPU builds, no GPU packages.

### A.3 Start the service

```bash
bash tools/run_wall_service.sh          # listens on 127.0.0.1:8177
```

or directly, with options:

```bash
.venv/bin/python pipeline/wall_service.py \
    --model pipeline/models/wall_student_convnext_tiny.onnx \
    --host 127.0.0.1 --port 8177 --scales 1024 --wall_thr 0.5 --threads 10
```

| flag | default | meaning |
|---|---|---|
| `--model` | `…convnext_tiny.onnx` | ConvNeXt-Tiny default; `…mbv3.onnx` for the fallback |
| `--port` | `8177` | TCP port the module connects to |
| `--host` | `127.0.0.1` | bind address (use `0.0.0.0` only for remote Foundry, §B.4) |
| `--scales` | `1024` | inference resolution(s); single-scale `1024` is the shipped default |
| `--wall_thr` | `0.5` | wall-probability threshold; **use `0.4` with the MobileNetV3 fallback** |
| `--threads` | CPU count − 2 | CPU threads for inference |

### A.4 Confirm it works

```bash
curl http://localhost:8177/health
# → {"status":"ok","model":"wall_student_convnext_tiny.onnx","scales":"1024","wall_thr":0.5}
```

Leave this terminal running (or install it as a background service — see
[§C Target system](#part-c--target-system-ryzen-3600--rx-6600--arch-linux) for a
systemd unit). The service must be running whenever you click "Detect Walls (ML)".

---

## Part B — Install the Foundry module

Pick **one** of the three methods.

### B.1 Method 1 — Install by manifest URL (easiest)

1. In Foundry: **Add-on Modules → Install Module**.
2. Paste the **Manifest URL** for this module (the `manifest` field in
   `vendor/auto-wall-companion/dist/module.json`, e.g. the project's published
   `awc-ml.json`) into the bottom field and click **Install**.

> ⚠️ **Module id:** this fork uses the id **`auto-wall-companion-ml`** on
> purpose. The original `auto-wall-companion` is *archived* on the Foundry
> registry, and installing under that id makes Foundry's "Update" button silently
> pull the old upstream package (which has **no** ML detection). Always install
> the `-ml` id.

### B.2 Method 2 — Manual zip

1. Take `vendor/auto-wall-companion/module.zip` (24 KB; ships prebuilt).
2. Extract it into your Foundry data folder as a new module directory:
   ```
   <FoundryData>/Data/modules/auto-wall-companion-ml/
       module.json
       scripts/module.js
       style.css
       ...
   ```
   (The folder name should be `auto-wall-companion-ml` to match the module id.)
3. Restart Foundry so it rescans modules.

Your `<FoundryData>` location:
- Linux: `~/.local/share/FoundryVTT/Data`
- macOS: `~/Library/Application Support/FoundryVTT/Data`
- Windows: `%localappdata%/FoundryVTT/Data`
- The Forge / hosted: use the host's module-upload wizard, §B.4.

### B.3 Method 3 — Build from source

```bash
cd vendor/auto-wall-companion
npm install
npm run build          # → dist/
node test/smoke.mjs    # headless smoke test, should pass
(cd dist && zip -r ../module.zip .)
```

Then install `module.zip` as in Method 2, or point Foundry at
`dist/module.json`. For a live dev loop that copies the build straight into a
local Foundry install:

```bash
FOUNDRY_DATA_PATH=/path/to/FoundryVTT/Data/modules npm run dev
```

### B.4 Remote / hosted Foundry

If Foundry runs somewhere other than your own machine (The Forge, a VPS, a
Docker host), the browser is on `https://…` and **cannot** reach
`http://localhost:8177` on your PC directly (mixed-content block + localhost
resolves to the *server*, not you). Two options:

- **HTTPS tunnel (recommended, what we verified):** expose the local service
  over HTTPS with a quick tunnel and point the module's Service URL at it:
  ```bash
  cloudflared tunnel --url http://localhost:8177
  # → prints https://<random>.trycloudflare.com  — use that as the Service URL
  ```
  (This is exactly how the in-game E2E test drove real Foundry v13 on The Forge:
  116 walls detected in 0.49 s over the tunnel.)
- **Run the service where Foundry can reach it** and bind it with
  `--host 0.0.0.0` (only on a trusted network — the endpoint has no auth).

---

## Part B.5 — Configure and use

1. Enable the module: **Game Settings → Manage Modules →** check
   **Auto Wall Companion (ML)** → Save.
2. Set the service URL: **Game Settings → Configure Settings → Auto Wall
   Companion (ML) → Service URL**. Default `http://localhost:8177` is correct for
   a local Foundry; use the tunnel URL from §B.4 for hosted Foundry.
3. Open a scene. **Set scene padding to 0** (Scene → Configure → Padding) for
   accurate wall positioning — the module warns you if it isn't.
4. Select the **Walls** tool in the left toolbar → click **Detect Walls (ML)**.
5. In the dialog, confirm the service URL and click **Detect walls**. Walls are
   created in batches of 100.

**Safety:** existing walls are never touched, and the last detection is undoable
from the same dialog (single undo step).

---

## Part C — Target system (Ryzen 3600 / RX 6600 / Arch Linux)

This section is tuned for the deployment box: **AMD Ryzen 5 3600 (6C/12T),
Radeon RX 6600 8 GB, 16 GB RAM, Arch Linux**, with the stated goal of keeping
**~20 % of resources free**.

### C.1 Why CPU-only here

The RX 6600 is **Navi 23 / gfx1032, which ROCm does not officially support**. The
usual `HSA_OVERRIDE_GFX_VERSION=10.3.0` workaround is broken on ROCm ≥ 6.4.3
(would need pinning to 6.4.1). So the service runs **on the CPU via
onnxruntime** — no ROCm install, nothing to pin, nothing to break on a rolling
Arch update. Expect **~2–2.5 s per map** single-scale for the ConvNeXt-Tiny
default on the Ryzen 3600 (no VNNI), which is fine for a one-shot import (the
MobileNetV3 fallback is ~1.3 s). A ROCm-free *GPU* path (ncnn + Vulkan/RADV)
exists but is **MobileNetV3-only** (see §C.6) — the ConvNeXt CPU path already
meets the budget.

### C.2 Install (Arch) — one command

`install.sh` (repo root) does the whole target-side setup autonomously: pacman
packages, model discovery, the venv + CPU runtime deps, the systemd user
service, and a self-test (health + a real detection).

```bash
# get the code onto the box (clone / rsync / git bundle — see §A.0), then:
cd ~/draw_maps
# get the model onto the box (git-ignored, 122 MB — USB / scp / download; §A.1);
# the installer searches pipeline/models, ~, ~/Downloads, and mounted USB drives.
bash install.sh
```

What makes it safe to just run (and re-run):

- **Resumable state machine.** Every step is recorded in `.install_state/` and
  RE-VERIFIED on each run: healthy steps are skipped in milliseconds, broken
  ones (e.g. a venv broken by a system-python upgrade, a deleted model file, a
  stale unit file after moving the repo) are repaired in place, then the
  install continues where it left off. `bash install.sh --status` shows the
  current state without changing anything.
- **Root only on demand.** When a step needs root it asks interactively: type
  your sudo password, or pick "I'll run it myself in another terminal" and the
  script waits, or abort (a later re-run resumes exactly there). Non-interactive
  runs print the exact `sudo` command and exit resumable.
- **Self-checking.** Port conflicts auto-advance to the next free port; the
  model file is validated by size + SHA-256; a wheel-less (too-new) Python
  falls back to Arch's `python-onnxruntime`/`python-opencv` packages; the final
  self-test POSTs a real image and requires a wall-detection answer.

On a box that **runs Foundry locally**, the installer also finds the Foundry
user-data folder (running process `--dataPath`, `Config/options.json`, or the
usual locations) and installs the module into
`<data>/Data/modules/auto-wall-companion-ml/` for you — so Part B below is only
needed if the auto-search can't find your Foundry (then pass `--foundry-data`)
or you install the module on a *different* machine. Enabling the module and
picking the world stays a one-time click in the Foundry UI (it is per-world and
unsafe to edit while Foundry runs); the module's Service URL already defaults to
the address the installer prints.

Useful flags: `--port N`, `--host ADDR`, `--threads N` (default ~80 % of cores),
`--vulkan` (MobileNetV3 + ncnn/Vulkan GPU path, §C.6), `--no-service` (skip the
systemd unit), `--no-module` (skip the Foundry-module install),
`--foundry-data DIR` (Foundry user-data folder if auto-search fails),
`--model-url` / `--model-src` (obtain the model), `--status`, `--reset`,
`--uninstall`. `--help` lists all. On success it prints the **Service URL** and
the module location.

The rest of §C explains what the script automates, in case you want to do it by
hand or tune it.

**Manual equivalent:**

```bash
sudo pacman -S --needed python git glib2 gcc-libs curl   # base + opencv runtime libs
# get the code onto the box (clone / rsync / git bundle — see §A.0), then:
cd ~/draw_maps
python3 -m venv .venv
.venv/bin/pip install -r pipeline/requirements-service.txt
# place wall_student_convnext_tiny.onnx into pipeline/models/  (see §A.1)
```

### C.3 Respect the 20%-free budget

The Ryzen 3600 has 12 threads; keeping ~20 % free means capping inference at
**~9–10 threads**:

```bash
.venv/bin/python pipeline/wall_service.py \
    --model pipeline/models/wall_student_convnext_tiny.onnx \
    --host 127.0.0.1 --port 8177 --scales 1024 --wall_thr 0.5 --threads 9
```

Memory is a non-issue: the model is 122 MB and peak working set stays well under
1 GB of the 16 GB — comfortably inside a ~12 GB budget. Expect ~2–2.5 s/map on
the Ryzen 3600 (single-scale 1024); fine for a one-shot import.

### C.4 Run it as a background service (systemd user unit)

So you don't have to keep a terminal open. Create
`~/.config/systemd/user/wall-service.service`:

```ini
[Unit]
Description=Auto Wall Companion ML service
After=network.target

[Service]
WorkingDirectory=%h/draw_maps
ExecStart=%h/draw_maps/.venv/bin/python pipeline/wall_service.py \
    --model pipeline/models/wall_student_convnext_tiny.onnx \
    --host 127.0.0.1 --port 8177 --scales 1024 --wall_thr 0.5 --threads 9
Restart=on-failure

[Install]
WantedBy=default.target
```

Then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now wall-service.service
systemctl --user status wall-service.service     # should be active (running)
curl http://localhost:8177/health                # confirm
```

`loginctl enable-linger $USER` keeps it running when you're not logged in, if you
want that.

### C.5 Local Foundry on the same box

If Foundry runs on this same machine, the default Service URL
`http://localhost:8177` just works — no tunnel needed. Only use §B.4's tunnel if
your Foundry is hosted elsewhere.

### C.6 Optional: GPU on the RX 6600 via Vulkan (ncnn, ROCm-free) — MobileNetV3 only

The CPU path already meets the latency budget, so this is optional. But the
RX 6600 *can* be used without ROCm through **ncnn + Vulkan (RADV)** — the same
Mesa driver the desktop uses, no gfx1032 workaround needed.

> **This path uses the MobileNetV3 fallback, not the ConvNeXt-Tiny default.**
> pnnx miscompiles the ConvNeXt decoder (a plain 3×3 conv emits `inf` → all-NaN
> output, fp16 *and* fp32 alike), so ConvNeXt-Tiny has no working ncnn/Vulkan
> build. Choosing Vulkan therefore trades quality 0.765 → 0.722 for GPU speed.
> If you want the 0.765 quality, stay on the ConvNeXt ONNX/CPU default.

**MobileNetV3 ncnn quality is identical to its ONNX** — verified at graph-F1
**0.722** (P0.796 R0.684) on the in-scope-32 set vs its ONNX 0.721; the fp16
weights match to within noise (wall-mask IoU 0.976).

Install the Vulkan runtime and ncnn:

```bash
sudo pacman -S vulkan-radeon vulkan-icd-loader   # RADV driver for the RX 6600
.venv/bin/pip install ncnn
vulkaninfo --summary | grep deviceName            # should list the RX 6600
```

The ncnn model files (`wall_student_mbv3.ncnn.param` + `.bin`, ~13 MB) ship
alongside the ONNX, or regenerate them from the ONNX with pnnx:

```bash
.venv/bin/pip install pnnx
.venv/bin/pnnx pipeline/models/wall_student_mbv3.onnx inputshape=[1,3,1024,1024]
# -> wall_student_mbv3.ncnn.param / .bin  (move into pipeline/models/)
```

Run the service on the GPU:

```bash
.venv/bin/python pipeline/wall_service.py \
    --backend ncnn --vulkan \
    --model pipeline/models/wall_student_mbv3.ncnn.param --port 8177
# /health -> {"status":"ok","backend":"ncnn",...}
```

Drop `--vulkan` to run ncnn on the CPU instead. Benchmark quality + latency on
this box before switching over:

```bash
# CPU:
.venv/bin/python pipeline/ncnn_eval.py --per_map --wall_thr 0.4
# Vulkan (RX 6600):
NCNN_VULKAN=1 .venv/bin/python pipeline/ncnn_eval.py --per_map --wall_thr 0.4
```

> **Note:** Vulkan latency was **not** benchmarked on the RX 6600 during
> development (the dev box has no Vulkan GPU) — run the `NCNN_VULKAN=1` command
> above on your machine to measure it. The quality parity (0.722) and the CPU
> path are both verified.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "Detect Walls (ML)" button missing | Module not enabled, or you installed the archived `auto-wall-companion` (no `-ml`). Enable **Auto Wall Companion (ML)** (§B.1 warning). |
| Dialog error "could not reach service" | Service not running (`curl http://localhost:8177/health`), wrong Service URL, or (hosted Foundry) mixed-content block → use the HTTPS tunnel (§B.4). |
| Model file missing on start | `wall_student_convnext_tiny.onnx` not in `pipeline/models/` — see §A.1. |
| Walls offset from the image | Scene padding not 0 — set Scene → Configure → Padding = 0 and re-run (§B.5). |
| Detection slow (> 3 s) | Reduce to single-scale (`--scales 1024`, default), raise `--threads`, close other CPU load. |
| `onnxruntime` warns about `/sys/class/drm/card0` | Harmless GPU-probe warning on headless/AMD boxes; the service runs on CPU regardless. |

---

## Updating the model later

The model is teacher-agnostic. After any teacher improvement, re-distill and
re-export (no module change needed — restart the service with the new file):

```bash
.venv/bin/python pipeline/train_student.py --encoder tu-convnext_tiny --pseudo corpus/distill_pl_p1 \
    --out pipeline/models/wall_student_tu_convnext_tiny.pt
.venv/bin/python pipeline/export_student_onnx.py \
    --ckpt pipeline/models/wall_student_tu_convnext_tiny.pt \
    --encoder tu-convnext_tiny \
    --out  pipeline/models/wall_student_convnext_tiny.onnx
systemctl --user restart wall-service.service      # if using the systemd unit
```

See `DEPLOYMENT.md` for the model/quality details and `DISTILL_PLAN.md` for the
distillation design.
