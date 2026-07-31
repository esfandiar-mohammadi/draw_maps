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

**Quality:** graph-F1 **0.765** on a held-out set of 32 in-scope maps, at
~1 s per map on a desktop CPU (~2–2.5 s on a Ryzen 3600) at 1024² inference.

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
| **Foundry VTT** | v12, v13 or v14 — **all three verified end-to-end in real containers** (see §C.7) |
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
| `--model` | `…convnext_tiny.onnx` | path to the model ONNX |
| `--port` | `8177` | TCP port the module connects to |
| `--host` | `127.0.0.1` | bind address (use `0.0.0.0` only for remote Foundry, §B.4) |
| `--scales` | `1024` | inference resolution(s); single-scale `1024` is the shipped default |
| `--wall_thr` | `0.5` | wall-probability threshold (the shipped model's operating point) |
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
- **Docker/Podman:** the host side of the volume mounted at `/data` (so
  `<host dir>/Data/modules/…`); for a *named* volume copy it in with
  `docker cp <dir> <container>:/data/Data/modules/`. `install.sh` does all of
  this for you — §C.6.
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

This is about Foundry running on **another machine** (The Forge, a VPS, a remote
Docker host): the browser is then on `https://…` and **cannot** reach
`http://localhost:8177` on your PC directly. Two options:

> Foundry in a container **on your own machine** is *not* this case — the module
> fetches from the browser, so `http://localhost:8177` is correct and no tunnel
> is needed. See §C.6.

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
break on a rolling Arch update. Expect **~2–2.5 s per map** single-scale on the
Ryzen 3600 — fine for a one-shot import.

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
  **Foundry in Docker/Podman is handled too — see §C.6.**
- **Three stages, and it pauses instead of failing.** Stage 1 is the service
  (fully automatic), stage 2 the module files, stage 3 the two clicks in
  Foundry's UI. If a stage needs something only you can do — most commonly
  joining the `docker` group, which only takes effect after a **new login** —
  the installer prints exactly what to do and stops with exit code 4. Nothing is
  lost: `bash install.sh` resumes at that very step.

Useful flags: `--port N`, `--host ADDR`, `--threads N` (default ~80 % of cores),
`--no-service` (skip the systemd unit), `--no-module` / `--service-only` (skip the
Foundry-module install), `--module-only` (only redo the module part),
`--foundry-data DIR` (Foundry user-data folder if auto-search fails),
`--docker-container NAME` (the Foundry container, if auto-detect picks wrong),
`--serve-module` / `--serve-port N` (hand the module to Foundry's own installer —
no Docker access and no root needed),
`--model-url` / `--model-src` (obtain the model), `--status`, `--reset`,
`--uninstall`. `--help` lists all.

**Manual equivalent:**

```bash
sudo pacman -S --needed python git glib2 gcc-libs curl unzip   # base + opencv runtime libs + module unzip
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

### C.7 Verified Foundry versions

Every major the manifest claims (`compatibility.minimum 12`, `verified 14`) was
driven end-to-end in a real `felddy/foundryvtt` container on a root-only named
volume: module installed, enabled, a scene created from a 1280×1280 battle map,
then **Detect Walls (ML)**:

| Foundry | module loads | toolbar button | walls detected | time |
|---|---|---|---|---|
| **v14.365** | yes | yes (`tools` object) | **198** | 1.9 s |
| **v13** | yes | yes (`tools` object) | **198** | 1.8 s |
| **v12** | yes | yes (`tools` array) | **198** | 1.5 s |

Screenshots: `docs/evidence/foundry-v1{2,3,4}-walls-detected.png`. Reproduce with
`tools/foundry_test_env.sh` + `tools/foundry_ui_drive.py e2e`.

> **Forward-looking caveat (v14):** v14 moved a scene's background onto its new
> **Level** documents; `Scene#background` still works through a deprecation shim
> (that is what the module reads), and Foundry warns that the shim *will* be
> removed. So the module works on v14 today, but a future major will need it to
> read the level's background instead.

### C.6 Foundry in a Docker/Podman container

This is fully supported and needs no manual copying — but it needs **one
permission**, because the module files have to be placed inside the container's
data volume and only the container runtime knows where that is.

**The service URL stays `http://localhost:8177`.** The module calls the service
from **your browser**, not from inside the container, so you do *not* have to
expose the port to the container or change any network setting.

**Docker access is not always required.** The installer tries, in order:

1. **No Docker at all — read the container's mount table.**
   `/proc/<pid>/mountinfo` of the containerized Foundry process is world-readable
   even though the process belongs to root, and its source field is the *host*
   path of every volume (a bind mount directly; a named volume as
   `/var/lib/docker/volumes/<name>/_data`). If that directory is writable by you
   — the normal case for `-v ~/foundrydata:/data` — the module is installed by a
   plain file copy: **no Docker group, no sudo, nothing to log out for.**
2. **Not writable? Ask the runtime** (needs Docker access) and copy through it —
   see below.
3. **No Docker access and not writable?** Either root (`sudo`, the installer
   offers it and hands the files to Foundry's uid afterwards) or
   **`--serve-module`**, which needs neither: see "Route without Docker" below.

When it does have Docker access:

1. It notices a containerized Foundry even without any Docker access — a Foundry
   process whose cgroup is a container cgroup.
2. It asks the runtime for the Foundry container (matching image or name) and
   for its mounts.
3. Then it picks the cheapest working route:
   - the volume is a **bind mount you can write** → plain file copy;
   - the volume is a **named volume** (`/var/lib/docker/volumes/…`, root-only) or
     a bind mount owned by Foundry's container uid (e.g. `421`, the
     `felddy/foundryvtt` default) → it copies **through the runtime**
     (`docker cp`) and hands the files to that uid inside the container. No sudo
     needed for this route.
4. Finally it reminds you to `docker restart <container>` so Foundry rescans its
   modules, then you enable the module in the UI (stage 3).

#### Route without Docker access *and* without root: let Foundry install it

Foundry's own installer takes a **Manifest URL**, fetches the zip named in the
manifest's `download` field and unpacks it into its own data folder — as the
container's own user. So the installer can simply hand the files over:

```bash
bash install.sh --serve-module          # add --serve-port N to pick the port
```

It serves the zip plus a manifest patched with a reachable `download`/`manifest`
URL and prints something like `http://192.168.1.23:8178/module.json`. Paste that
into Foundry's **Add-on Modules → Install Module**, click Install — the installer
sees the download in its access log, confirms it, and stops the server. Then
enable the module in the world as usual.

Notes: the URL deliberately uses a routable host address, because `localhost`
inside the container is the container itself; if the printed address isn't
reachable, the command prints alternatives (bridge gateway, and
`host.docker.internal` for Docker Desktop). This route cannot be verified from
outside the container, so the installer reports what Foundry fetched rather than
claiming the files are in place. The manifest field is documented here:
<https://foundryvtt.com/article/module-development/>.

**If you are not allowed to talk to Docker** *and* the volume isn't writable, the
installer stops (exit 4) and prints these choices — pick one and re-run:

```bash
# A) grant yourself Docker access (recommended, one time)
sudo usermod -aG docker "$USER"
#    then LOG OUT and LOG IN again — a group change only applies to new
#    sessions; in the current terminal:  newgrp docker
bash install.sh

# B) let the installer use sudo for the docker commands
sudo -v && bash install.sh

# C) skip Docker entirely: name the host directory that is mounted as /data
bash install.sh --foundry-data /host/path/to/foundrydata

# D) let Foundry install it itself — needs neither Docker nor root
bash install.sh --serve-module

# E) service only now, module later
bash install.sh --no-module
```

Auto-detection picking the wrong container (several containers match "foundry")?
Name it: `bash install.sh --module-only --docker-container my-foundry`.

Uninstall is container-aware: `bash install.sh --uninstall` removes the module
*inside* the container and never touches host paths.

Verified with real containers, two suites, all green:
- `tools/test_install_module.sh` (51 assertions) — named volume, writable bind
  mount, bind mount owned by uid 421, outdated copy replaced, no-access pause,
  resume, uninstall, `--foundry-data`, `--status`.
- `tools/test_install_nodocker.sh` (25 assertions) — with a `docker` CLI stubbed
  to fail like a socket-permission denial: host-path discovery via
  `/proc/<pid>/mountinfo`, the named-volume pause, and the full `--serve-module`
  hand-off (patched manifest, routable URL, download detected) with `curl`
  standing in for Foundry, plus the nothing-detectable case (skip, never fail).
- A **stopped** Foundry container is handled too: the module is written into its
  volume by a throwaway sidecar (no `docker exec`, no host root), so you can shut
  Foundry down before installing.

Note on the evidence: the dev box's account *is* in the `docker` group, so the
`docker cp` route was tested with access. The target may not have it — which is
why the no-access routes are tested with the runtime stubbed to fail exactly like
a socket-permission denial, not merely reasoned about.

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
| Installer: "permission denied … docker.sock" / can't reach the Foundry container | You are not in the `docker` group: `sudo usermod -aG docker "$USER"`, then **log out and back in** (or `newgrp docker`), then re-run `bash install.sh`. Alternatives in §C.6. |
| Installer stops with "ONE STEP NEEDS YOU" (exit 4) | By design, not an error: do the printed action, then re-run `bash install.sh` — it resumes at that step. |
| Module installed but Foundry doesn't list it (Docker) | Foundry only rescans modules at startup: `docker restart <container>`. |
| After a container restart: "Foundry VTT cannot start in this directory which is already locked" | A killed Foundry leaves a lock behind. Remove it and start again: `docker run --rm -u 0 -v <your-data-volume>:/data alpine rm -rf /data/Config/options.json.lock` then `docker start <container>`. Prefer `docker stop` (graceful) over `docker kill`/`restart` under load. |
| Installer stops at "No onnxruntime for this Python" | Arch rolled Python ahead of the onnxruntime wheels, and `python-onnxruntime` is **not** in the official repos. Install it from the AUR (`yay -S python-onnxruntime`) or build the venv with an older Python, then re-run. |
| Foundry runs in Docker and Detect Walls says the service is unreachable | The module calls the service **from your browser**. `http://localhost:8177` is right only if the browser runs on the machine hosting the service; from another device use that machine's LAN address (`--host 0.0.0.0`, trusted network only) or the tunnel from §B.4. |
| Several containers match "foundry" | Name the right one: `bash install.sh --module-only --docker-container NAME`. |

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
