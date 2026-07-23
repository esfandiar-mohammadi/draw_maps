#!/usr/bin/env bash
#
# deploy_arch.sh — fully autonomous deploy of the Auto Wall Companion (ML)
# companion service on the target box: Arch Linux, Ryzen 3600 / RX 6600, CPU-only.
#
# What it does, end to end:
#   1. preflight (Arch? repo root? python? sudo?)
#   2. install system packages via pacman  (python, git, glib2, curl, ...)
#   3. obtain the ONNX model  (already present / --model-url / --model-src)
#   4. create the venv + pip-install the CPU runtime deps
#   5. install + start a systemd *user* service (survives logout via linger)
#   6. self-test: /health + a real detection POST, fail loudly if either breaks
#
# It is idempotent — safe to re-run. Nothing here needs CUDA/ROCm; the RX 6600's
# gfx1032 is ROCm-unsupported and the model runs on the CPU (see INSTALL.md §C.1).
# The optional ROCm-free *GPU* path (ncnn+Vulkan) is MobileNetV3-only; enable it
# with --vulkan (installs vulkan-radeon + ncnn and switches to the mbv3 model).
#
# This installs the SERVICE only. The Foundry *module* is browser-side — install
# it separately per INSTALL.md Part B (it just needs the Service URL printed here).
#
# Usage:
#   bash tools/deploy_arch.sh [options]
#     --port N            listen port           (default 8177)
#     --host ADDR         bind address          (default 127.0.0.1)
#     --threads N         inference threads      (default: ~80% of cores)
#     --model-url URL     download the ONNX model from URL if not present
#     --model-src PATH    copy the ONNX model from a local path if not present
#     --vulkan            MobileNetV3 + ncnn/Vulkan GPU path (RX 6600 / RADV)
#     --no-service        set everything up but do NOT install the systemd unit
#     --yes               non-interactive (assume yes; default is already non-interactive)
#     -h | --help         this help
#
set -euo pipefail

# ---------- pretty logging -------------------------------------------------
if [ -t 1 ]; then C_B=$'\e[1m'; C_G=$'\e[32m'; C_Y=$'\e[33m'; C_R=$'\e[31m'; C_0=$'\e[0m'; else C_B=; C_G=; C_Y=; C_R=; C_0=; fi
step() { printf '%s\n' "${C_B}==> $*${C_0}"; }
ok()   { printf '%s\n' "${C_G}  ✓ $*${C_0}"; }
warn() { printf '%s\n' "${C_Y}  ! $*${C_0}"; }
die()  { printf '%s\n' "${C_R}  ✗ $*${C_0}" >&2; exit 1; }

# ---------- defaults / args ------------------------------------------------
PORT=8177
HOST=127.0.0.1
THREADS=""
MODEL_URL=""
MODEL_SRC=""
VULKAN=0
INSTALL_SERVICE=1

while [ $# -gt 0 ]; do
  case "$1" in
    --port)      PORT="$2"; shift 2;;
    --host)      HOST="$2"; shift 2;;
    --threads)   THREADS="$2"; shift 2;;
    --model-url) MODEL_URL="$2"; shift 2;;
    --model-src) MODEL_SRC="$2"; shift 2;;
    --vulkan)    VULKAN=1; shift;;
    --no-service) INSTALL_SERVICE=0; shift;;
    --yes)       shift;;
    -h|--help)   sed -n '2,40p' "$0"; exit 0;;
    *) die "unknown option: $1 (see --help)";;
  esac
done

# ---------- 1. preflight ---------------------------------------------------
step "Preflight"

command -v pacman >/dev/null 2>&1 || die "pacman not found — this script targets Arch Linux."
ok "Arch Linux (pacman present)"

# Locate repo root = parent of this script's dir. Run everything from there.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO"
[ -f pipeline/wall_service.py ] || die "pipeline/wall_service.py not found under $REPO — run from inside the repo."
ok "repo root: $REPO"

# sudo for pacman + linger. Non-root user with passwordless sudo is the happy path.
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  command -v sudo >/dev/null 2>&1 || die "not root and sudo not installed — install sudo or run as root."
  SUDO="sudo"
fi
ok "privilege escalation: ${SUDO:-<running as root>}"

# Model selection depends on --vulkan.
if [ "$VULKAN" -eq 1 ]; then
  MODEL_REL="pipeline/models/wall_student_mbv3.ncnn.param"
  ONNX_REL="pipeline/models/wall_student_mbv3.onnx"   # ncnn path still wants the .bin sibling; onnx kept for reference
  WALL_THR=0.4
  BACKEND=ncnn
else
  MODEL_REL="pipeline/models/wall_student_convnext_tiny.onnx"
  ONNX_REL="$MODEL_REL"
  WALL_THR=0.5
  BACKEND=onnx
fi

# ---------- 2. system packages --------------------------------------------
step "Installing system packages (pacman)"
PKGS=(python git glib2 curl)
# opencv-python-headless wheel needs libstdc++/libgomp (gcc-libs) at runtime.
PKGS+=(gcc-libs)
if [ "$VULKAN" -eq 1 ]; then
  PKGS+=(vulkan-radeon vulkan-icd-loader)
fi
# --needed skips already-installed packages -> idempotent, fast on re-run.
$SUDO pacman -Sy --needed --noconfirm "${PKGS[@]}"
ok "packages present: ${PKGS[*]}"

PYBIN="$(command -v python3 || command -v python)"
[ -n "$PYBIN" ] || die "python not found after install"
ok "python: $PYBIN ($("$PYBIN" --version 2>&1))"

# ---------- 3. obtain the model -------------------------------------------
step "Locating the model ($MODEL_REL)"
mkdir -p pipeline/models
need_model() { [ ! -f "$REPO/$MODEL_REL" ]; }

if need_model; then
  if [ -n "$MODEL_SRC" ]; then
    [ -f "$MODEL_SRC" ] || die "--model-src '$MODEL_SRC' does not exist"
    cp -v "$MODEL_SRC" "$REPO/$MODEL_REL"
    # ncnn needs the .bin sibling too
    if [ "$VULKAN" -eq 1 ]; then
      SRC_BIN="${MODEL_SRC%.param}.bin"
      [ -f "$SRC_BIN" ] && cp -v "$SRC_BIN" "$REPO/${MODEL_REL%.param}.bin" || warn "no .bin next to --model-src; copy it manually"
    fi
  elif [ -n "$MODEL_URL" ]; then
    step "Downloading model from $MODEL_URL"
    curl -fL --retry 3 -o "$REPO/$MODEL_REL" "$MODEL_URL" || die "model download failed"
    if [ "$VULKAN" -eq 1 ]; then
      warn "ncnn needs the .bin sibling too — pass it separately or use --model-src"
    fi
  fi
fi

if need_model; then
  cat >&2 <<EOF
${C_R}  ✗ Model file missing: $MODEL_REL${C_0}
    It is git-ignored (122 MB) and CANNOT be regenerated here (no CUDA GPU).
    Provide it one of these ways and re-run:
      • copy it onto this box, then:   --model-src /path/to/$(basename "$MODEL_REL")
      • host it somewhere, then:       --model-url https://.../$(basename "$MODEL_REL")
      • or scp it into place:          scp devbox:$REPO/$MODEL_REL $REPO/pipeline/models/
EOF
  exit 1
fi
# Weight bytes live in the .bin for ncnn (the .param is a tiny text header),
# and in the .onnx itself for the CPU path — sanity-check whichever is large.
if [ "$VULKAN" -eq 1 ]; then
  WEIGHTS="$REPO/${MODEL_REL%.param}.bin"
  [ -f "$WEIGHTS" ] || die "ncnn .bin missing next to the .param ($WEIGHTS) — copy it with --model-src"
else
  WEIGHTS="$REPO/$MODEL_REL"
fi
MODEL_SIZE=$(stat -c%s "$WEIGHTS")
[ "$MODEL_SIZE" -gt 1000000 ] || die "model weights $WEIGHTS are suspiciously small ($MODEL_SIZE bytes) — truncated?"
ok "model present ($((MODEL_SIZE/1024/1024)) MB weights)"

# ---------- 4. venv + pip --------------------------------------------------
step "Python virtualenv + runtime deps"
if [ ! -x "$REPO/.venv/bin/python" ]; then
  "$PYBIN" -m venv "$REPO/.venv"
  ok "created .venv"
else
  ok ".venv already exists"
fi
VENV_PY="$REPO/.venv/bin/python"
"$VENV_PY" -m pip install --upgrade pip >/dev/null
"$VENV_PY" -m pip install -r pipeline/requirements-service.txt
if [ "$VULKAN" -eq 1 ]; then
  "$VENV_PY" -m pip install "ncnn>=1.0.20240102"
fi
# Prove the imports resolve on THIS machine's wheels before we wire up a service.
"$VENV_PY" - <<'PY' || die "runtime import check failed — see error above"
import onnxruntime, cv2, numpy
print(f"  onnxruntime {onnxruntime.__version__}, opencv {cv2.__version__}, numpy {numpy.__version__}")
PY
ok "runtime deps installed and importable"

# ---------- threads (80% of cores, keep ~20% free) ------------------------
if [ -z "$THREADS" ]; then
  CORES=$(nproc)
  THREADS=$(( CORES * 8 / 10 )); [ "$THREADS" -lt 1 ] && THREADS=1
fi
ok "inference threads: $THREADS (of $(nproc) cores)"

# ---------- run-service command (shared by manual + systemd) --------------
if [ "$VULKAN" -eq 1 ]; then
  RUN_ARGS=(--backend ncnn --vulkan --model "$MODEL_REL" --wall_thr "$WALL_THR" \
            --host "$HOST" --port "$PORT" --scales 1024 --threads "$THREADS")
else
  RUN_ARGS=(--model "$MODEL_REL" --wall_thr "$WALL_THR" \
            --host "$HOST" --port "$PORT" --scales 1024 --threads "$THREADS")
fi

# ---------- 5. systemd user service ---------------------------------------
UNIT_STARTED=0
if [ "$INSTALL_SERVICE" -eq 1 ]; then
  step "Installing systemd user service (wall-service.service)"
  if [ "$(id -u)" -eq 0 ]; then
    warn "running as root — installing a *system* unit instead of a user unit"
    UNIT="/etc/systemd/system/wall-service.service"
    RELOAD=("systemctl" "daemon-reload"); ENABLE=("systemctl" "enable" "--now" "wall-service.service")
  else
    # Keep the user service alive after logout (SSH deploy needs this).
    DEPLOY_USER="$(id -un)"
    $SUDO loginctl enable-linger "$DEPLOY_USER" 2>/dev/null && ok "lingering enabled for $DEPLOY_USER" || warn "could not enable linger (service stops on logout)"
    mkdir -p "$HOME/.config/systemd/user"
    UNIT="$HOME/.config/systemd/user/wall-service.service"
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    RELOAD=("systemctl" "--user" "daemon-reload"); ENABLE=("systemctl" "--user" "enable" "--now" "wall-service.service")
  fi

  # Build ExecStart string from RUN_ARGS.
  EXEC="$REPO/.venv/bin/python pipeline/wall_service.py ${RUN_ARGS[*]}"
  cat > "$UNIT" <<EOF
[Unit]
Description=Auto Wall Companion (ML) companion service
After=network.target

[Service]
WorkingDirectory=$REPO
ExecStart=$EXEC
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
EOF
  ok "wrote $UNIT"

  if "${RELOAD[@]}" 2>/dev/null && "${ENABLE[@]}" 2>/dev/null; then
    UNIT_STARTED=1
    ok "service enabled and started"
  else
    warn "systemctl could not start the unit here (no user D-Bus session over SSH?)."
    warn "The unit file is installed; start it from a login session with:"
    warn "  systemctl --user enable --now wall-service.service"
  fi
fi

# ---------- start a throwaway instance if the unit isn't running ----------
# So the self-test can run even when systemctl --user isn't available.
TMP_PID=""
health_url="http://$HOST:$PORT/health"
if ! curl -fsS "$health_url" >/dev/null 2>&1; then
  step "Starting a temporary instance for the self-test"
  "$REPO/.venv/bin/python" pipeline/wall_service.py "${RUN_ARGS[@]}" >/tmp/wall_service_selftest.log 2>&1 &
  TMP_PID=$!
  for _ in $(seq 1 40); do curl -fsS "$health_url" >/dev/null 2>&1 && break; sleep 0.5; done
fi

# ---------- 6. self-test ---------------------------------------------------
step "Self-test"
HEALTH="$(curl -fsS "$health_url" 2>/dev/null)" || die "service not answering on $health_url"
ok "health: $HEALTH"

# Find a real image to POST: repo test tiles, else synthesize one.
TEST_IMG=""
for cand in corpus/fa_tiles/images/*.png corpus/real_uvtt/*/*.png; do
  [ -f "$cand" ] && { TEST_IMG="$cand"; break; }
done
if [ -z "$TEST_IMG" ]; then
  TEST_IMG="/tmp/wall_selftest.png"
  "$REPO/.venv/bin/python" - "$TEST_IMG" <<'PY'
import sys, numpy as np, cv2
img = np.full((512,512,3), 40, np.uint8)
cv2.rectangle(img,(60,60),(452,452),(200,200,200),6)   # a room the model should wall
cv2.imwrite(sys.argv[1], img)
PY
fi
DET="$(curl -fsS -X POST --data-binary @"$TEST_IMG" "http://$HOST:$PORT/detect" 2>/dev/null)" || die "detection request failed"
COUNT="$(printf '%s' "$DET" | "$REPO/.venv/bin/python" -c 'import sys,json;print(json.load(sys.stdin)["count"])' 2>/dev/null || echo "?")"
ELAPSED="$(printf '%s' "$DET" | "$REPO/.venv/bin/python" -c 'import sys,json;print(json.load(sys.stdin)["elapsed_s"])' 2>/dev/null || echo "?")"
[ "$COUNT" != "?" ] && [ "$COUNT" -ge 0 ] 2>/dev/null || die "detection returned no valid result: $DET"
ok "detection on $(basename "$TEST_IMG"): $COUNT walls in ${ELAPSED}s"

# Stop the throwaway instance (the systemd unit, if started, keeps running).
[ -n "$TMP_PID" ] && { kill "$TMP_PID" 2>/dev/null || true; ok "temporary instance stopped"; }

# ---------- summary --------------------------------------------------------
step "Done"
echo
echo "  Service URL for the Foundry module:  ${C_B}http://$HOST:$PORT${C_0}"
echo "  Backend: $BACKEND   model: $(basename "$MODEL_REL")   wall_thr: $WALL_THR   threads: $THREADS"
if [ "$INSTALL_SERVICE" -eq 1 ] && [ "$UNIT_STARTED" -eq 1 ]; then
  echo "  Running as a systemd service. Manage it with:"
  if [ "$(id -u)" -eq 0 ]; then
    echo "    systemctl status|restart|stop wall-service.service"
  else
    echo "    systemctl --user status|restart|stop wall-service.service"
  fi
elif [ "$INSTALL_SERVICE" -eq 1 ]; then
  echo "  ${C_Y}Unit installed but not started here — run from a login shell:${C_0}"
  echo "    systemctl --user enable --now wall-service.service"
else
  echo "  Service not installed (--no-service). Start it manually with:"
  echo "    .venv/bin/python pipeline/wall_service.py ${RUN_ARGS[*]}"
fi
echo
echo "  Next: install the Foundry module (browser side) — INSTALL.md Part B."
echo "  Hosted/remote Foundry (e.g. The Forge) needs an HTTPS tunnel to reach this box — INSTALL.md §B.4."
