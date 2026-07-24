# Wall Annotation Companion

**Automatically annotate the walls on a Foundry VTT battle map.** Import a map,
click one button, and the walls are drawn as native Foundry `Wall` documents —
working vision and movement blocking in seconds instead of tracing hundreds of
segments by hand.

> Not to be confused with the archived **auto-wall-companion** module on the
> Foundry registry. This is a distinct project with its own module id
> (`wall-annotation-companion`) and its own ML wall detector.

---

## What it is

Wall Annotation Companion turns a battle-map image into editable Foundry walls
using a small convolutional neural network that runs **locally on your CPU** —
no cloud, no API keys, no GPU required. Your maps never leave your machine.

It has **two parts** you install separately:

```
 ┌─────────────────────────┐        HTTP         ┌──────────────────────────┐
 │  Foundry VTT             │  POST scene image   │  companion service       │
 │  "Detect Walls (ML)"     │ ──────────────────▶ │  (Python, runs on YOUR   │
 │  button (this module)    │ ◀────────────────── │   machine, CPU-only)     │
 └─────────────────────────┘     walls JSON       └──────────────────────────┘
        in the browser                                  32 M-param CNN
```

- **The companion service** — a tiny Python HTTP server that runs the wall
  detector on your computer.
- **The Foundry module** — adds the *"Detect Walls (ML)"* button, sends the
  scene image to the service, and turns the returned segments into walls
  (correcting for scene padding and background scale, so they land where they
  should). Existing walls are never touched, and every detection is undoable.

## How the detection works

The map image is segmented into a **wall-probability map** and a **junction
heatmap** by the neural network, which are then turned into a clean *planar
graph* — a few long, snapped, editable segments rather than thousands of pixel
specks. The shipped model is a **ConvNeXt-Tiny U-Net (≈32 M params)** distilled
from a much larger DINOv2 ViT-g teacher, so it keeps most of the teacher's
quality at a fraction of the size and runs comfortably on a CPU.

**Quality** (graph-F1 on a held-out set of 32 in-scope maps, the same metric
used for the teacher):

| model | params | graph-F1 | CPU latency @1024² |
|---|---|---|---|
| DINOv2 ViT-g teacher | 1.1 B | 0.786 | GPU-class |
| **ConvNeXt-Tiny student — shipped default** | **32 M** | **0.765** | ~1 s desktop · ~2–2.5 s Ryzen 3600 |
| MobileNetV3-L student — fallback | 6.7 M | 0.741 | ~0.65 s |

It works best on maps with clear built structure — buildings, dungeons, caves,
towers — the intended scope. Wide-open organic terrain (forests, rivers, open
water) is out of scope and intentionally left sparse. See `DEPLOYMENT.md` for
the full model/quality story and `DISTILL_PLAN.md` for how the student was
trained.

---

## Quick start

On the machine that will run the detection (and, ideally, Foundry too):

```bash
git clone https://github.com/esfandiar-mohammadi/draw_maps.git ~/draw_maps
cd ~/draw_maps
bash install.sh
```

That's it. `install.sh` is a **fully autonomous, resumable installer** (Arch
Linux): it installs system + Python dependencies, **downloads the model**,
starts the service as a background (systemd) service, and — if Foundry runs on
the same box — installs the Foundry module into your Foundry data folder for
you. It re-verifies every step on each run, so it's safe to just re-run if
anything goes wrong. When it finishes it prints the **Service URL** to use in
Foundry (default `http://localhost:8177`).

Then, one time in Foundry: **Manage Modules → enable Wall Annotation Companion →
Save**, open a scene, and click **Detect Walls (ML)**.

The rest of this document is the detailed / manual guide, and the target-machine
notes (Arch Linux, Ryzen 3600 / RX 6600).

---

## 0. Prerequisites

| Component | Requirement |
|---|---|
| **Foundry VTT** | v12, v13, or v14 (verified on v13/v14) |
| **Python** | 3.10+ (3.12 tested) — for the companion service |
| **OS** | Linux, macOS, or Windows. Service is pure CPU — **no GPU, no CUDA, no ROCm required** (`install.sh` targets Arch Linux; the service itself runs anywhere) |
| **RAM** | ~1 GB free while the service runs (measured peak ~750 MB at 1024²) |
| **Node.js** | 18+ — **only** if you build the module from source (Part B, method 3) |

The service and the Foundry client must reach each other over HTTP. The common
case (Foundry on the same machine, browser at `localhost`) works out of the box.
Remote/hosted Foundry (e.g. The Forge) needs one extra step — see
[§B.4 Remote / hosted Foundry](#b4-remote--hosted-foundry).

---

## Part A — Install the companion service

### A.0 Get the code onto the box

```bash
git clone https://github.com/esfandiar-mohammadi/draw_maps.git ~/draw_maps
cd ~/draw_maps
```

No git on the target? Copy the working tree instead — `install.sh` finds its own
repo root wherever you drop it and needs no git:

```bash
rsync -av --exclude .venv --exclude .install_state \
      --exclude node_modules --exclude corpus \
      <devbox>:/path/to/draw_maps/  ~/draw_maps/
```

### A.1 Get the model

The detector weights live in
**`pipeline/models/wall_student_convnext_tiny.onnx`** (122 MB, fp32). It is *not*
in git (too large). You normally don't fetch it by hand — **`install.sh`
downloads it automatically** from the project host if it isn't already present.
To place it yourself, use any of:

- **Download** it directly:
  ```bash
  curl -L -o pipeline/models/wall_student_convnext_tiny.onnx \
    http://mohammadi.eu/dateien/wall_student_convnext_tiny.onnx
  ```
- **Point the installer at a copy:** `bash install.sh --model-src /path/to.onnx`
  (or `--model-url <url>` for a different host).
- **Regenerate it** from the teacher pseudo-labels (needs a CUDA GPU):
  ```bash
  .venv/bin/python pipeline/train_student.py --encoder tu-convnext_tiny \
      --pseudo corpus/distill_pl_p1 \
      --out pipeline/models/wall_student_tu_convnext_tiny.pt
  .venv/bin/python pipeline/export_student_onnx.py \
      --ckpt pipeline/models/wall_student_tu_convnext_tiny.pt \
      --encoder tu-convnext_tiny \
      --out  pipeline/models/wall_student_convnext_tiny.onnx
  ```

> **Smaller/faster fallback:** the MobileNetV3-L student
> (`wall_student_mbv3.onnx`, 26 MB, graph-F1 0.741 **@wall_thr 0.4**) is also
> available and is the only model with an ncnn/Vulkan GPU path (§C.6). Use it
> with `--model …mbv3.onnx --wall_thr 0.4`.

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

Leave it running, or install it as a background service — see
[§C Target system](#part-c--target-system-ryzen-3600--rx-6600--arch-linux) for a
systemd unit. The service must be running whenever you click "Detect Walls (ML)".

---

## Part B — Install the Foundry module

On a machine that runs Foundry locally, **`install.sh` already did this** (it
finds the Foundry data folder and drops the module in). Do it by hand only if
the installer couldn't find Foundry, or you run Foundry on a different machine.
Pick **one** method.

### B.1 Method 1 — Install by manifest URL

1. In Foundry: **Add-on Modules → Install Module**.
2. Paste the module's **Manifest URL** and click **Install**. (This project isn't
   published to the Foundry registry, so unless you host `module.json` yourself,
   use Method 2 or 3.)

> ⚠️ **Not the same as "Auto Wall Companion".** This is a distinct project with
> its own id **`wall-annotation-companion`**. Don't install the archived
> `auto-wall-companion` on the registry (a different, unmaintained module with no
> ML detection) — it gives you nothing from here.

### B.2 Method 2 — Manual zip

1. Take `foundry_module/wall-annotation-companion.zip` (ships prebuilt in the
   repo; build source in `vendor/auto-wall-companion/`).
2. Extract it into your Foundry data folder as a new module directory:
   ```
   <FoundryData>/Data/modules/wall-annotation-companion/
       module.json
       scripts/module.js
       style.css
       ...
   ```
   (Folder name must be `wall-annotation-companion`, matching the module id.)
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

Then install `module.zip` as in Method 2, or point Foundry at `dist/module.json`.
For a live dev loop that copies the build into a local Foundry install:

```bash
FOUNDRY_DATA_PATH=/path/to/FoundryVTT/Data/modules npm run dev
```

### B.4 Remote / hosted Foundry

If Foundry runs somewhere other than your own machine (The Forge, a VPS, a
Docker host), the browser is on `https://…` and **cannot** reach
`http://localhost:8177` on your PC directly. Two options:

- **HTTPS tunnel (recommended, verified):** expose the local service over HTTPS
  and point the module's Service URL at it:
  ```bash
  cloudflared tunnel --url http://localhost:8177
  # → prints https://<random>.trycloudflare.com  — use that as the Service URL
  ```
  (This is exactly how the in-game E2E test drove real Foundry v13 on The Forge:
  116 walls detected in 0.49 s over the tunnel.)
- **Run the service where Foundry can reach it** and bind with `--host 0.0.0.0`
  (only on a trusted network — the endpoint has no auth).

### B.5 Configure and use

1. Enable the module: **Game Settings → Manage Modules →** check
   **Wall Annotation Companion** → Save.
2. Set the service URL: **Game Settings → Configure Settings → Wall Annotation
   Companion → Service URL**. Default `http://localhost:8177` is correct for a
   local Foundry; use the tunnel URL from §B.4 for hosted Foundry.
3. Open a scene. **Set scene padding to 0** (Scene → Configure → Padding) for
   accurate wall positioning — the module warns you if it isn't.
4. Select the **Walls** tool in the left toolbar → click **Detect Walls (ML)**.
5. Confirm the service URL in the dialog and click **Detect walls**. Walls are
   created in batches of 100.

**Safety:** existing walls are never touched, and the last detection is undoable
from the same dialog (single undo step).

---

## Part C — Target system (Ryzen 3600 / RX 6600 / Arch Linux)

Tuned for the reference deployment box: **AMD Ryzen 5 3600 (6C/12T), Radeon
RX 6600 8 GB, 16 GB RAM, Arch Linux**, keeping **~20 % of resources free**.

### C.1 Why CPU-only here

The RX 6600 is **Navi 23 / gfx1032, which ROCm does not officially support**
(the `HSA_OVERRIDE_GFX_VERSION=10.3.0` workaround is broken on ROCm ≥ 6.4.3). So
the service runs **on the CPU via onnxruntime** — nothing to pin, nothing to
break on a rolling Arch update. Expect **~2–2.5 s per map** single-scale for the
ConvNeXt-Tiny default on the Ryzen 3600 (the MobileNetV3 fallback is ~1.3 s) —
fine for a one-shot import. A ROCm-free *GPU* path (ncnn + Vulkan/RADV) exists
but is **MobileNetV3-only** (§C.6).

### C.2 Install (Arch) — one command

`install.sh` (repo root) does the whole target-side setup autonomously: pacman
packages, model download, the venv + CPU runtime deps, the systemd user service,
the local Foundry-module install, and a self-test (health + a real detection).

```bash
git clone https://github.com/esfandiar-mohammadi/draw_maps.git ~/draw_maps
cd ~/draw_maps
bash install.sh
```

What makes it safe to just run (and re-run):

- **Resumable state machine.** Every step is recorded in `.install_state/` and
  RE-VERIFIED on each run: healthy steps skip in milliseconds, broken ones (a
  venv broken by a system-python upgrade, a deleted model, a stale unit file
  after moving the repo) are repaired in place, then it continues. `bash
  install.sh --status` shows the state without changing anything.
- **Root only on demand.** When a step needs root it asks: type your sudo
  password, or pick "I'll run it myself in another terminal" and it waits, or
  abort (a re-run resumes there). Non-interactive runs print the exact `sudo`
  command and exit resumable.
- **Self-checking.** It downloads the model if missing and validates it by size +
  SHA-256; port conflicts auto-advance to a free port; a too-new Python falls
  back to Arch's `python-onnxruntime`/`python-opencv` packages; the final
  self-test POSTs a real image and requires a wall-detection answer.
- **Local Foundry module install.** It finds the Foundry user-data folder
  (running process `--dataPath`, `Config/options.json`, or the usual locations)
  and installs the module into `<data>/Data/modules/wall-annotation-companion/`.
  Enabling it + choosing the world stays a one-time Foundry-UI click (per-world,
  unsafe to edit while Foundry runs); the Service URL already defaults correctly.

Useful flags: `--port N`, `--host ADDR`, `--threads N` (default ~80 % of cores),
`--vulkan` (MobileNetV3 + ncnn/Vulkan GPU path, §C.6), `--no-service` (skip the
systemd unit), `--no-module` (skip the Foundry-module install),
`--foundry-data DIR` (Foundry user-data folder if auto-search fails),
`--model-url` / `--model-src` (obtain the model), `--status`, `--reset`,
`--uninstall`. `--help` lists all.

**Manual equivalent:**

```bash
sudo pacman -S --needed python git glib2 gcc-libs curl   # base + opencv runtime libs
git clone https://github.com/esfandiar-mohammadi/draw_maps.git ~/draw_maps && cd ~/draw_maps
python3 -m venv .venv
.venv/bin/pip install -r pipeline/requirements-service.txt
# fetch the model (see §A.1) into pipeline/models/
```

### C.3 Respect the 20%-free budget

The Ryzen 3600 has 12 threads; keeping ~20 % free means capping inference at
**~9–10 threads** (`--threads 9`). `install.sh` computes ~80 % of your cores
automatically. Memory is a non-issue: peak working set stays well under 1 GB.

### C.4 Run it as a background service (systemd user unit)

`install.sh` sets this up for you. To do it by hand, create
`~/.config/systemd/user/wall-service.service`:

```ini
[Unit]
Description=Wall Annotation Companion service
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

```bash
systemctl --user daemon-reload
systemctl --user enable --now wall-service.service
systemctl --user status wall-service.service     # active (running)
curl http://localhost:8177/health                # confirm
loginctl enable-linger "$USER"                    # keep running without a login session
```

### C.5 Local Foundry on the same box

If Foundry runs on this machine, the default Service URL `http://localhost:8177`
just works — no tunnel. Only use §B.4's tunnel for hosted Foundry.

### C.6 Optional: GPU on the RX 6600 via Vulkan (ncnn, ROCm-free) — MobileNetV3 only

Optional (the CPU path already meets the budget). The RX 6600 can be used without
ROCm via **ncnn + Vulkan (RADV)** — the same Mesa driver the desktop uses.

> **This path uses the MobileNetV3 fallback, not the ConvNeXt-Tiny default.**
> pnnx miscompiles the ConvNeXt decoder (a plain 3×3 conv emits `inf` → all-NaN,
> fp16 *and* fp32), so ConvNeXt-Tiny has no working ncnn/Vulkan build. Vulkan
> therefore trades quality 0.765 → 0.722 for GPU speed. For 0.765, stay on the
> ConvNeXt ONNX/CPU default.

Enable it with `bash install.sh --vulkan`, or by hand:

```bash
sudo pacman -S vulkan-radeon vulkan-icd-loader   # RADV driver for the RX 6600
.venv/bin/pip install ncnn
.venv/bin/python pipeline/wall_service.py --backend ncnn --vulkan \
    --model pipeline/models/wall_student_mbv3.ncnn.param --wall_thr 0.4 --port 8177
```

The ncnn model files (`wall_student_mbv3.ncnn.param` + `.bin`) ship in the repo,
or regenerate them from the ONNX with `pnnx`. MobileNetV3 ncnn quality is
verified identical to its ONNX (graph-F1 0.722; wall-mask IoU 0.976). Vulkan
*latency* was not benchmarked on real RX 6600 hardware during development — run
`NCNN_VULKAN=1 .venv/bin/python pipeline/ncnn_eval.py --per_map --wall_thr 0.4`
on the target to measure it.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "Detect Walls (ML)" button missing | Module not enabled, or you installed the unrelated archived `auto-wall-companion` by mistake. Enable **Wall Annotation Companion** (§B.1). |
| Dialog error "could not reach service" | Service not running (`curl http://localhost:8177/health`), wrong Service URL, or (hosted Foundry) mixed-content block → use the HTTPS tunnel (§B.4). |
| Model file missing on start | `wall_student_convnext_tiny.onnx` not in `pipeline/models/` — `install.sh` downloads it; or fetch manually (§A.1). |
| Walls offset from the image | Scene padding not 0 — set Scene → Configure → Padding = 0 and re-run (§B.5). |
| Detection slow (> 3 s) | Keep single-scale (`--scales 1024`, default), raise `--threads`, close other CPU load. |
| `onnxruntime` warns about `/sys/class/drm/card0` | Harmless GPU-probe warning on headless/AMD boxes; the service runs on CPU regardless. |

---

## Updating the model later

The model is teacher-agnostic; the module never changes. After any teacher
improvement, re-distill and re-export (§A.1), drop the new `.onnx` into
`pipeline/models/`, and restart the service
(`systemctl --user restart wall-service.service`).

## Credits & license

The Foundry module's wall copy/paste plumbing derives from
[ThreeHats/auto-wall-companion](https://github.com/ThreeHats/auto-wall-companion)
(MIT); the ML wall detection, the companion service, and this project are new
work. See `DEPLOYMENT.md` for the model/quality details and `DISTILL_PLAN.md` for
the distillation design.
