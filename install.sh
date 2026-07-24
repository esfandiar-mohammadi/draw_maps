#!/usr/bin/env bash
#
# install.sh — one-command, fully autonomous installer for the Auto Wall
# Companion (ML) service on the target box (Arch Linux, Ryzen 3600 / RX 6600).
#
#     bash install.sh
#
# That is all. The script:
#   • figures out what is already installed and skips it,
#   • finds the model file by itself (repo, ~, ~/Downloads, USB mounts, ...),
#   • asks for root ONLY when needed — and lets you either type your sudo
#     password, run the command yourself in another terminal, or abort,
#   • remembers every completed step in .install_state/ and, when re-run,
#     RE-VERIFIES each previous step: healthy steps are skipped, broken steps
#     are repaired in place, then it continues where it left off,
#   • self-tests at the end (health endpoint + a real wall detection).
#
# Every step is a (verify, do, fix) triple. verify_* is authoritative — the
# state file is a hint, never trusted blindly. So: python upgraded and broke
# the venv? verify catches it, fix rebuilds it. Model file deleted? verify
# catches it, discovery runs again. Unit file stale after the repo moved?
# verify diffs it, fix rewrites + restarts.
#
# Flags (all optional):
#   --port N          preferred port (default 8177; auto-advances if occupied)
#   --host ADDR       bind address (default 127.0.0.1)
#   --threads N       inference threads (default ≈80% of cores → 9 on a 3600)
#   --model-src PATH  use this model file instead of searching
#   --model-url URL   download the model from URL if not found locally
#   --vulkan          use the MobileNetV3+ncnn/Vulkan GPU path instead of the
#                     ConvNeXt/CPU default (RX 6600 via RADV; lower quality
#                     0.722 vs 0.765 — see INSTALL.md §C.6)
#   --no-service      do everything except the systemd unit (foreground use)
#   --status          show what is / is not done, change nothing, exit
#   --reset           forget all recorded state (verifies still protect you)
#   --uninstall       stop + remove the systemd service (keeps venv/model)
#   -h | --help       this text
#
# ─────────────────────────────────────────────────────────────────────────────
# 0. Shell guard FIRST (before any bashism): user's login shell is zsh, and
#    'sh install.sh' must also work — re-exec under bash if we are not bash.
# ─────────────────────────────────────────────────────────────────────────────
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
if [ "${BASH_VERSINFO[0]}" -lt 4 ]; then echo "need bash >= 4"; exit 1; fi

set -u -o pipefail

# ─────────────────────────────────────────────────────────────────────────────
# Constants baked at release time
# ─────────────────────────────────────────────────────────────────────────────
MODEL_ONNX="wall_student_convnext_tiny.onnx"
MODEL_ONNX_SHA256="461bb18ff2377926f24c0055182e1c3163b93d05584b58fc6675ee0fbe2274fe"
MODEL_ONNX_MINBYTES=100000000        # 122 MB nominal; >100 MB = not truncated
MODEL_NCNN_PARAM="wall_student_mbv3.ncnn.param"   # its .bin sibling is required too
MODEL_NCNN_BIN_SHA256="f6d53f8bd7eefc3ecff2012dbbce48700abb3181b251b8589fe9cf93554fe808"
MODEL_NCNN_MINBYTES=10000000
WALL_THR_ONNX="0.5"                  # ConvNeXt-Tiny operating point
WALL_THR_NCNN="0.4"                  # MobileNetV3 operating point
UNIT_NAME="wall-service.service"

# ─────────────────────────────────────────────────────────────────────────────
# Pretty output + logging (everything also lands in .install_state/install.log)
# ─────────────────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  C_B=$'\e[1m'; C_G=$'\e[32m'; C_Y=$'\e[33m'; C_R=$'\e[31m'; C_C=$'\e[36m'; C_0=$'\e[0m'
else C_B=""; C_G=""; C_Y=""; C_R=""; C_C=""; C_0=""; fi
LOGFILE=""   # set once the state dir exists
_log()  { [ -n "$LOGFILE" ] && printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOGFILE" || true; }
step()  { printf '%s\n' "${C_B}==> $*${C_0}";        _log "STEP  $*"; }
ok()    { printf '%s\n' "${C_G}  ✓ $*${C_0}";        _log "OK    $*"; }
skip()  { printf '%s\n' "${C_C}  ↷ $* (already done, verified)${C_0}"; _log "SKIP  $*"; }
warn()  { printf '%s\n' "${C_Y}  ! $*${C_0}";        _log "WARN  $*"; }
fail()  { printf '%s\n' "${C_R}  ✗ $*${C_0}" >&2;    _log "FAIL  $*"; }
die()   { fail "$*"; echo; echo "  Fix the issue above and simply re-run:  bash install.sh"
          echo "  (completed steps are remembered and will be skipped)"; exit 1; }
run_logged() { _log "RUN   $*"; "$@" >>"${LOGFILE:-/dev/null}" 2>&1; }

# ─────────────────────────────────────────────────────────────────────────────
# Arguments
# ─────────────────────────────────────────────────────────────────────────────
PORT_PREF=8177; HOST=127.0.0.1; THREADS=""; MODEL_SRC=""; MODEL_URL=""
VULKAN=0; NO_SERVICE=0; DO_STATUS=0; DO_RESET=0; DO_UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --port)      PORT_PREF="$2"; shift 2;;
    --host)      HOST="$2"; shift 2;;
    --threads)   THREADS="$2"; shift 2;;
    --model-src) MODEL_SRC="$2"; shift 2;;
    --model-url) MODEL_URL="$2"; shift 2;;
    --vulkan)    VULKAN=1; shift;;
    --no-service) NO_SERVICE=1; shift;;
    --status)    DO_STATUS=1; shift;;
    --reset)     DO_RESET=1; shift;;
    --uninstall) DO_UNINSTALL=1; shift;;
    -h|--help)   sed -n '3,/^# *-h | --help/p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) die "unknown option: $1 (see --help)";;
  esac
done

# ─────────────────────────────────────────────────────────────────────────────
# Locate the repo. Normally this script sits in the repo root; if someone
# copied install.sh elsewhere, search the usual places for the pipeline.
# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO=""
for cand in "$SCRIPT_DIR" "$SCRIPT_DIR/.." "$PWD" "$HOME/draw_maps" "$HOME/src/draw_maps" "$HOME/code/draw_maps"; do
  if [ -f "$cand/pipeline/wall_service.py" ]; then REPO="$(cd "$cand" && pwd)"; break; fi
done
if [ -z "$REPO" ]; then
  # last resort: shallow filesystem search under $HOME (bounded depth, quiet)
  found="$(find "$HOME" -maxdepth 4 -name wall_service.py -path "*/pipeline/*" 2>/dev/null | head -1)"
  [ -n "$found" ] && REPO="$(cd "$(dirname "$found")/.." && pwd)"
fi
[ -n "$REPO" ] || die "could not find the draw_maps repo (pipeline/wall_service.py).
    Clone/copy the repo first, then run install.sh from inside it."
cd "$REPO" || die "cannot cd into $REPO"

STATE="$REPO/.install_state"; mkdir -p "$STATE"; LOGFILE="$STATE/install.log"
_log "―――――― install.sh invoked: $0 $* (repo=$REPO)"

if [ "$DO_RESET" -eq 1 ]; then rm -f "$STATE"/step.* "$STATE"/chosen.*; ok "state cleared"; fi

# state helpers ───────────────────────────────────────────────────────────────
mark()   { date '+%F %T' > "$STATE/step.$1"; }
marked() { [ -f "$STATE/step.$1" ]; }
remember(){ printf '%s' "$2" > "$STATE/chosen.$1"; }
recall() { cat "$STATE/chosen.$1" 2>/dev/null; }

# ─────────────────────────────────────────────────────────────────────────────
# Root-privilege helper. Tries, in order:
#   already root → passwordless sudo → interactive menu (password / run-it-
#   yourself-and-wait / abort) → non-interactive: print command + exit(3),
#   the re-run resumes exactly here.
# ─────────────────────────────────────────────────────────────────────────────
run_root() {  # run_root <description> <cmd...>
  local desc="$1"; shift
  if [ "$(id -u)" -eq 0 ]; then run_logged "$@"; return $?; fi
  if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    _log "ROOT(passwordless sudo) $*"; sudo "$@" >>"$LOGFILE" 2>&1; return $?
  fi
  if [ -t 0 ] && [ -t 1 ]; then
    echo
    echo "  ${C_B}Root privileges needed:${C_0} $desc"
    echo "      ${C_C}sudo $*${C_0}"
    echo "    [1] run it with sudo now (asks for your password)"
    echo "    [2] I'll run it MYSELF in another terminal — wait for me"
    echo "    [3] abort the installation (re-running later resumes here)"
    local choice
    while true; do
      read -r -p "  choose [1/2/3]: " choice
      case "$choice" in
        1) _log "ROOT(interactive sudo) $*"
           if sudo "$@" 2>&1 | tee -a "$LOGFILE"; then return 0; else return 1; fi;;
        2) echo "  Run this in another terminal, then press ENTER here:"
           echo "      ${C_C}sudo $*${C_0}"
           read -r -p "  (ENTER when done) " _
           return 0;;   # caller's verify decides whether it truly worked
        3) die "aborted at your request before: sudo $*";;
        *) echo "  please answer 1, 2 or 3";;
      esac
    done
  fi
  # non-interactive (piped/cron/CI): cannot ask — leave precise instructions.
  fail "root needed but no TTY to ask. Run this yourself, then re-run install.sh:"
  echo "      sudo $*" >&2
  exit 3
}

# ═════════════════════════════════════════════════════════════════════════════
# STEP DEFINITIONS — each step is verify_X + do_X. verify is authoritative.
# ═════════════════════════════════════════════════════════════════════════════

# ── step 1: system sanity ────────────────────────────────────────────────────
verify_sanity() {
  command -v pacman >/dev/null 2>&1 || { fail "not an Arch system (no pacman)"; return 1; }
  [ "$(uname -m)" = "x86_64" ] || warn "arch is $(uname -m), expected x86_64 (continuing)"
  # disk: venv ~500MB + model 122MB + headroom
  local free_kb; free_kb=$(df -Pk "$REPO" | awk 'NR==2{print $4}')
  [ "${free_kb:-0}" -gt 1500000 ] || { fail "less than 1.5 GB free on $(df -P "$REPO" | awk 'NR==2{print $6}')"; return 1; }
  # RAM: service peak ~750MB
  local avail_kb; avail_kb=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
  [ "${avail_kb:-0}" -gt 1200000 ] || warn "less than 1.2 GB RAM available right now — service may swap"
  return 0
}
do_sanity() { verify_sanity; }

# ── step 2: pacman packages ──────────────────────────────────────────────────
PKGS_BASE=(python gcc-libs glib2 curl)          # gcc-libs/glib2: opencv wheel runtime
PKGS_VULKAN=(vulkan-radeon vulkan-icd-loader)
pkg_missing() {
  local missing=() p
  for p in "${PKGS_BASE[@]}"; do pacman -Qq "$p" >/dev/null 2>&1 || missing+=("$p"); done
  if [ "$VULKAN" -eq 1 ]; then
    for p in "${PKGS_VULKAN[@]}"; do pacman -Qq "$p" >/dev/null 2>&1 || missing+=("$p"); done
  fi
  printf '%s\n' "${missing[@]:-}"
}
verify_pacman() {
  local m; m="$(pkg_missing)"; [ -z "$m" ] && return 0
  fail "missing packages: $(echo "$m" | tr '\n' ' ')"; return 1
}
do_pacman() {
  # stale db lock (crashed pacman) blocks everything — detect and clear it.
  if [ -f /var/lib/pacman/db.lck ] && ! pgrep -x pacman >/dev/null 2>&1; then
    warn "stale pacman lock found (no pacman running)"
    run_root "remove stale pacman database lock" rm -f /var/lib/pacman/db.lck
  fi
  local missing; missing="$(pkg_missing)"; [ -z "$missing" ] && return 0
  # shellcheck disable=SC2086
  set -- $missing
  # try WITHOUT refreshing first (no partial-upgrade risk on a live Arch box);
  # if the local db is too old (404s), fall back to a full -Syu.
  if ! run_root "install packages: $*" pacman -S --needed --noconfirm "$@"; then
    warn "plain install failed (stale package database?) — retrying with full sync (-Syu)"
    run_root "full system sync + install: $*" pacman -Syu --needed --noconfirm "$@" \
      || { fail "pacman failed — check network / mirrors (see $LOGFILE)"; return 1; }
  fi
  return 0
}

# ── step 3: locate/obtain the model ─────────────────────────────────────────
model_target() {
  if [ "$VULKAN" -eq 1 ]; then echo "pipeline/models/$MODEL_NCNN_PARAM"
  else echo "pipeline/models/$MODEL_ONNX"; fi
}
model_ok() {  # <path> — size sane? hash known?
  local p="$1" minb sha want
  if [ "$VULKAN" -eq 1 ]; then
    [ -f "$p" ] && [ -f "${p%.param}.bin" ] || return 1
    minb=$MODEL_NCNN_MINBYTES; want=$MODEL_NCNN_BIN_SHA256
    [ "$(stat -c%s "${p%.param}.bin")" -ge "$minb" ] || return 1
    sha=$(sha256sum "${p%.param}.bin" | cut -d' ' -f1)
  else
    [ -f "$p" ] || return 1
    minb=$MODEL_ONNX_MINBYTES; want=$MODEL_ONNX_SHA256
    [ "$(stat -c%s "$p")" -ge "$minb" ] || return 1
    sha=$(sha256sum "$p" | cut -d' ' -f1)
  fi
  if [ "$sha" != "$want" ]; then
    warn "model checksum differs from the released build (retrained model? continuing)"
  fi
  return 0
}
verify_model() { model_ok "$REPO/$(model_target)"; }
do_model() {
  local tgt; tgt="$REPO/$(model_target)"; mkdir -p "$REPO/pipeline/models"
  local base; base="$(basename "$tgt")"
  # 1) explicit source wins
  if [ -n "$MODEL_SRC" ]; then
    [ -f "$MODEL_SRC" ] || { fail "--model-src '$MODEL_SRC' not found"; return 1; }
    cp -f "$MODEL_SRC" "$tgt"
    [ "$VULKAN" -eq 1 ] && [ -f "${MODEL_SRC%.param}.bin" ] && cp -f "${MODEL_SRC%.param}.bin" "${tgt%.param}.bin"
    model_ok "$tgt" && return 0
  fi
  # 2) hunt the filesystem: places a downloaded/copied model plausibly lives
  step "searching the filesystem for $base"
  local hits=() d
  for d in "$REPO/pipeline/models" "$HOME/Downloads" "$HOME/Desktop" "$HOME" \
           /run/media/*/* /media/*/* /mnt/* /tmp; do
    [ -d "$d" ] || continue
    while IFS= read -r f; do hits+=("$f"); done \
      < <(find "$d" -maxdepth 3 -name "$base" -size +10M 2>/dev/null | head -3)
  done
  local h
  for h in "${hits[@]:-}"; do
    [ -n "$h" ] || continue
    ok "found candidate: $h"
    cp -f "$h" "$tgt" 2>/dev/null || true
    if [ "$VULKAN" -eq 1 ] && [ -f "${h%.param}.bin" ]; then cp -f "${h%.param}.bin" "${tgt%.param}.bin"; fi
    model_ok "$tgt" && { ok "using $h"; return 0; }
    warn "candidate failed validation (too small / incomplete) — keeping looking"
  done
  # 3) download
  if [ -n "$MODEL_URL" ]; then
    step "downloading model from $MODEL_URL"
    curl -fL --retry 3 --max-time 1800 -o "$tgt.part" "$MODEL_URL" \
      && mv -f "$tgt.part" "$tgt" && model_ok "$tgt" && return 0
    rm -f "$tgt.part"; fail "download failed or file invalid"; return 1
  fi
  fail "model '$base' not found anywhere.
    It is NOT in git (too large) and CANNOT be built on this machine (needs a
    CUDA GPU). Get it onto this box (USB stick / scp / download), then either:
      • drop it into  $REPO/pipeline/models/   and re-run  bash install.sh
      • or:  bash install.sh --model-src /path/to/$base
      • or:  bash install.sh --model-url https://your-host/$base"
  return 1
}

# ── step 4: python venv (self-healing after system python upgrades) ─────────
venv_healthy() { "$REPO/.venv/bin/python" -c "import sys; sys.exit(0)" >/dev/null 2>&1; }
verify_venv() {
  [ -x "$REPO/.venv/bin/python" ] || { fail ".venv missing"; return 1; }
  venv_healthy || { fail ".venv broken (system python upgraded since it was made?)"; return 1; }
  return 0
}
do_venv() {
  if [ -d "$REPO/.venv" ] && ! venv_healthy; then
    warn "rebuilding broken venv"
    rm -rf "$REPO/.venv"
  fi
  [ -d "$REPO/.venv" ] || run_logged python3 -m venv "$REPO/.venv" \
    || run_logged python3 -m venv --system-site-packages "$REPO/.venv" \
    || { fail "could not create venv"; return 1; }
  verify_venv
}

# ── step 5: python deps, with wheel-availability fallback chain ──────────────
#   pip → pip --pre → pacman python-* packages + venv rebuilt with
#   --system-site-packages. (A brand-new system python may predate wheels for
#   onnxruntime/opencv; Arch's own python-onnxruntime/python-opencv then save us.)
verify_pydeps() {
  "$REPO/.venv/bin/python" - >/dev/null 2>&1 <<'PY' || { fail "python deps not importable"; return 1; }
import onnxruntime, cv2, numpy
from skimage.morphology import skeletonize   # graph_infer runtime dep
PY
  if [ "$VULKAN" -eq 1 ]; then
    "$REPO/.venv/bin/python" -c "import ncnn" >/dev/null 2>&1 || { fail "ncnn not importable"; return 1; }
  fi
  return 0
}
do_pydeps() {
  local pip="$REPO/.venv/bin/pip"
  run_logged "$pip" install --upgrade pip || true
  if run_logged "$pip" install -r pipeline/requirements-service.txt; then
    :
  elif run_logged "$pip" install --pre onnxruntime opencv-python-headless "numpy>=2" scikit-image; then
    warn "used pre-release wheels (release wheels not yet available for this python)"
  else
    warn "no usable wheels for this python — falling back to Arch's python packages"
    run_root "install python deps from the Arch repos" \
      pacman -S --needed --noconfirm python-onnxruntime python-opencv python-numpy python-scikit-image \
      || { fail "neither pip wheels nor Arch packages available for onnxruntime/opencv"; return 1; }
    warn "rebuilding venv with --system-site-packages so it sees the Arch packages"
    rm -rf "$REPO/.venv"
    run_logged python3 -m venv --system-site-packages "$REPO/.venv" || return 1
  fi
  if [ "$VULKAN" -eq 1 ]; then
    run_logged "$pip" install "ncnn>=1.0.20240102" \
      || { fail "pip could not install ncnn (needed for --vulkan)"; return 1; }
  fi
  verify_pydeps
}

# ── step 6: choose port + threads (persisted, so re-runs stay consistent) ───
port_free() {  # true if nothing listens on 127.0.0.1:$1 (fd opens in a subshell)
  if (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; then return 1; else return 0; fi
}
port_is_ours() {  # an older instance of OUR service already on this port?
  curl -fsS --max-time 3 "http://127.0.0.1:$1/health" 2>/dev/null | grep -q '"model"'
}
verify_config() { [ -n "$(recall port)" ] && [ -n "$(recall threads)" ]; }
do_config() {
  local port="$PORT_PREF" tries=0
  while ! port_free "$port"; do
    if port_is_ours "$port"; then ok "port $port already serves an older install (will be replaced)"; break; fi
    warn "port $port is taken by another program — trying $((port+1))"
    port=$((port+1)); tries=$((tries+1))
    [ "$tries" -gt 20 ] && { fail "no free port in $PORT_PREF..$port"; return 1; }
  done
  remember port "$port"
  local thr="$THREADS"
  if [ -z "$thr" ]; then
    thr=$(( $(nproc) * 8 / 10 )); [ "$thr" -lt 1 ] && thr=1   # keep ~20% CPU free
  fi
  remember threads "$thr"
  ok "port=$port threads=$thr (of $(nproc) cores)"
}

# service command, derived from remembered choices ───────────────────────────
service_args() {
  local port thr; port="$(recall port)"; thr="$(recall threads)"
  if [ "$VULKAN" -eq 1 ]; then
    echo "--backend ncnn --vulkan --model pipeline/models/$MODEL_NCNN_PARAM --wall_thr $WALL_THR_NCNN --host $HOST --port $port --scales 1024 --threads $thr"
  else
    echo "--model pipeline/models/$MODEL_ONNX --wall_thr $WALL_THR_ONNX --host $HOST --port $port --scales 1024 --threads $thr"
  fi
}

# ── step 7: systemd user unit ────────────────────────────────────────────────
UNIT_PATH="$HOME/.config/systemd/user/$UNIT_NAME"
unit_expected() {
  cat <<EOF
[Unit]
Description=Auto Wall Companion (ML) companion service
After=network.target

[Service]
WorkingDirectory=$REPO
ExecStart=$REPO/.venv/bin/python pipeline/wall_service.py $(service_args)
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
EOF
}
user_systemd_available() {
  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  systemctl --user is-enabled default.target >/dev/null 2>&1 \
    || systemctl --user list-units >/dev/null 2>&1
}
verify_unit() {
  [ "$NO_SERVICE" -eq 1 ] && return 0
  [ -f "$UNIT_PATH" ] || { fail "unit file missing"; return 1; }
  diff -q <(unit_expected) "$UNIT_PATH" >/dev/null 2>&1 \
    || { fail "unit file outdated (path/port/threads changed)"; return 1; }
  return 0
}
do_unit() {
  [ "$NO_SERVICE" -eq 1 ] && return 0
  mkdir -p "$(dirname "$UNIT_PATH")"
  unit_expected > "$UNIT_PATH"
  ok "wrote $UNIT_PATH"
  # linger: keeps the user service alive with no session (e.g. after reboot,
  # before login). Desktop boxes usually allow this via polkit; fall back to root.
  if ! loginctl show-user "$(id -un)" 2>/dev/null | grep -q '^Linger=yes'; then
    if ! run_logged loginctl enable-linger "$(id -un)"; then
      run_root "enable lingering (service runs without an open session)" \
        loginctl enable-linger "$(id -un)" \
        || warn "linger not enabled — service stops when you log out (still fine for desktop use)"
    fi
  fi
  return 0
}

# ── step 8: (re)start the service ────────────────────────────────────────────
verify_running() {
  local port health; port="$(recall port)"
  health="$(curl -fsS --max-time 4 "http://$HOST:$port/health" 2>/dev/null)" || return 1
  printf '%s' "$health" | grep -q '"status": *"ok"' || return 1
  # it must be serving the model THIS install is about (catches mode switches)
  printf '%s' "$health" | grep -qF "\"$(basename "$(model_target)")\"" \
    || { fail "a service is up on port $port but serves a different model — will restart it"; return 1; }
}
do_running() {
  local port; port="$(recall port)"
  # stop a previous plain-background instance of ours (mode/port switches)
  if [ -f "$STATE/service.pid" ]; then
    kill "$(cat "$STATE/service.pid")" 2>/dev/null && sleep 1
    rm -f "$STATE/service.pid"
  fi
  if [ "$NO_SERVICE" -eq 1 ]; then
    step "starting the service in the background (--no-service: no systemd)"
    : > "$STATE/service.out"
    # shellcheck disable=SC2046
    nohup "$REPO/.venv/bin/python" pipeline/wall_service.py $(service_args) \
      >> "$STATE/service.out" 2>&1 &
    echo $! > "$STATE/service.pid"
  else
    if user_systemd_available; then
      rm -f "$STATE/service.out"     # diagnostics should come from journalctl now
      run_logged systemctl --user daemon-reload
      run_logged systemctl --user enable "$UNIT_NAME"
      run_logged systemctl --user restart "$UNIT_NAME"
    else
      warn "systemd --user is not reachable from this shell (SSH without a session bus?)"
      warn "starting a plain background instance instead; after your next login run:"
      warn "    systemctl --user enable --now $UNIT_NAME"
      : > "$STATE/service.out"
      # shellcheck disable=SC2046
      nohup "$REPO/.venv/bin/python" pipeline/wall_service.py $(service_args) \
        >> "$STATE/service.out" 2>&1 &
      echo $! > "$STATE/service.pid"
    fi
  fi
  # wait for it to come up (model load can take a few seconds)
  local _i
  for _i in $(seq 1 60); do verify_running && return 0; sleep 0.5; done
  fail "service did not answer on http://$HOST:$port/health within 30 s — log tail:"
  if [ -s "$STATE/service.out" ]; then tail -15 "$STATE/service.out" >&2
  else journalctl --user -u "$UNIT_NAME" -n 15 --no-pager >&2 2>/dev/null || true; fi
  return 1
}

# ── step 9: end-to-end self-test (a REAL detection, not just /health) ───────
verify_selftest() {
  marked selftest || return 1
  [ "$(recall selftest_model)" = "$(basename "$(model_target)")" ] || return 1
  verify_running
}
do_selftest() {
  local port img det count elapsed; port="$(recall port)"
  img="$STATE/selftest.png"
  # prefer a real corpus tile if the repo has one; else synthesize a room
  local cand; cand=$(find "$REPO/corpus" -name "*.png" -path "*fa_tiles*" 2>/dev/null | head -1)
  if [ -n "$cand" ]; then cp -f "$cand" "$img"; else
    "$REPO/.venv/bin/python" - "$img" <<'PY' || return 1
import sys, numpy as np, cv2
im = np.full((512,512,3), 40, np.uint8)
cv2.rectangle(im,(60,60),(452,452),(200,200,200),6)
cv2.line(im,(256,60),(256,452),(200,200,200),6)
cv2.imwrite(sys.argv[1], im)
PY
  fi
  det="$(curl -fsS --max-time 120 -X POST --data-binary @"$img" "http://$HOST:$port/detect")" \
    || { fail "detection request failed"; return 1; }
  count=$(printf '%s' "$det" | "$REPO/.venv/bin/python" -c 'import sys,json;print(json.load(sys.stdin)["count"])' 2>/dev/null)
  elapsed=$(printf '%s' "$det" | "$REPO/.venv/bin/python" -c 'import sys,json;print(json.load(sys.stdin)["elapsed_s"])' 2>/dev/null)
  [ -n "$count" ] || { fail "detection returned no parseable result: ${det:0:200}"; return 1; }
  ok "live detection works: $count walls in ${elapsed}s"
  remember selftest_model "$(basename "$(model_target)")"
  mark selftest
}

# ═════════════════════════════════════════════════════════════════════════════
# Special modes
# ═════════════════════════════════════════════════════════════════════════════
if [ "$DO_UNINSTALL" -eq 1 ]; then
  step "uninstalling the service"
  systemctl --user disable --now "$UNIT_NAME" 2>/dev/null && ok "unit stopped+disabled" || true
  rm -f "$UNIT_PATH" && ok "unit file removed" || true
  systemctl --user daemon-reload 2>/dev/null || true
  [ -f "$STATE/service.pid" ] && kill "$(cat "$STATE/service.pid")" 2>/dev/null && ok "background instance stopped"
  rm -f "$STATE"/step.* "$STATE"/chosen.* "$STATE/service.pid"
  ok "state cleared (venv and model kept; delete $REPO/.venv manually if wanted)"
  exit 0
fi

STEPS=(sanity pacman model venv pydeps config unit running selftest)
declare -A DESC=(
  [sanity]="system sanity (Arch, disk, RAM)"
  [pacman]="system packages (pacman)"
  [model]="model file"
  [venv]="python virtualenv"
  [pydeps]="python runtime deps"
  [config]="port + thread configuration"
  [unit]="systemd user service"
  [running]="service running"
  [selftest]="end-to-end self-test"
)

if [ "$DO_STATUS" -eq 1 ]; then
  step "install status (verify only, changing nothing)"
  for s in "${STEPS[@]}"; do
    if "verify_$s" >/dev/null 2>&1; then ok "${DESC[$s]}"; else fail "${DESC[$s]}"; fi
  done
  exit 0
fi

# ═════════════════════════════════════════════════════════════════════════════
# MAIN LOOP — verify → (skip | do → verify) for every step, in order.
# A re-run walks the same list: healthy steps are skipped in milliseconds,
# broken ones are repaired, and installation continues from there.
# ═════════════════════════════════════════════════════════════════════════════
echo "${C_B}Auto Wall Companion (ML) — autonomous installer${C_0}"
echo "repo: $REPO    log: $LOGFILE"
[ "$VULKAN" -eq 1 ] && warn "--vulkan: MobileNetV3+ncnn GPU path (quality 0.722 vs CPU default 0.765)"

for s in "${STEPS[@]}"; do
  step "${DESC[$s]}"
  if "verify_$s"; then
    if marked "$s"; then skip "${DESC[$s]}"; else ok "${DESC[$s]} (was already in place)"; mark "$s"; fi
    continue
  fi
  # not healthy → (re)do it, then verify again. This is the rewind+repair path.
  if ! "do_$s"; then
    die "step failed: ${DESC[$s]}"
  fi
  if ! "verify_$s"; then
    die "step '${DESC[$s]}' ran but its result does not verify — see $LOGFILE"
  fi
  mark "$s"
  ok "${DESC[$s]}"
done

# ═════════════════════════════════════════════════════════════════════════════
# Summary
# ═════════════════════════════════════════════════════════════════════════════
PORT="$(recall port)"
echo
echo "${C_G}${C_B}Installation complete and verified.${C_0}"
echo
echo "  Service URL for the Foundry module:   ${C_B}http://$HOST:$PORT${C_0}"
echo "  Model: $(basename "$(model_target)")   threads: $(recall threads)"
if [ "$NO_SERVICE" -eq 0 ]; then
  echo "  Runs as a systemd user service:"
  echo "      systemctl --user status|restart|stop $UNIT_NAME"
  echo "      journalctl --user -u $UNIT_NAME -f        # live log"
fi
echo
echo "  Next (one-time, in the browser): install the Foundry module —"
echo "  INSTALL.md Part B. Set its Service URL to the address above."
echo "  Hosted Foundry (The Forge etc.) additionally needs an HTTPS tunnel"
echo "  (INSTALL.md §B.4):  cloudflared tunnel --url http://localhost:$PORT"
