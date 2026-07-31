#!/usr/bin/env bash
#
# install.sh — one-command, fully autonomous installer for the Wall Annotation
# Companion service on the target box (Arch Linux, Ryzen 3600 / RX 6600).
#
#     bash install.sh
#
# That is all. The script:
#   • figures out what is already installed and skips it,
#   • finds the model file by itself (repo, ~, ~/Downloads, USB mounts, ...) and
#     downloads it from the project host if it isn't present anywhere,
#   • finds the LOCAL Foundry data folder and installs the module into it
#     (so a box running Foundry locally needs no manual copy) — including the
#     case where Foundry runs in a Docker/Podman container: then the files go
#     into the container's data volume,
#   • PAUSES with precise instructions whenever a step needs a human action
#     (e.g. joining the 'docker' group, which only takes effect after a new
#     login) and continues exactly there when you re-run it,
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
#   --model-url URL   download the model from URL (default: the project host,
#                     http://mohammadi.eu/dateien/...) if not found locally
#   --foundry-data D  Foundry user-data dir (the folder containing Data/), if the
#                     auto-search can't find your local Foundry install. For a
#                     containerized Foundry this is the HOST side of the volume
#                     that is mounted as /data (skips all Docker access).
#   --docker-container N  name/id of the Foundry container (skips auto-detect)
#   --no-module       do not install the Foundry module (service only)
#   --service-only    alias for --no-module (stage 1 only)
#   --module-only     only (re)install the Foundry module, touch nothing else
#                     (useful after you granted yourself Docker access)
#   --serve-module    serve the module over HTTP and print a Manifest URL, so
#                     FOUNDRY ITSELF installs it (Add-on Modules → Install
#                     Module). Needs neither Docker access nor root — the way in
#                     when Foundry runs in a container you may not touch.
#   --serve-port N    port for --serve-module (default 8178, auto-advances)
#   --vulkan          use the MobileNetV3+ncnn/Vulkan GPU path instead of the
#                     ConvNeXt/CPU default (RX 6600 via RADV; lower quality
#                     0.722 vs 0.765 — see DEPLOYMENT.md §1; model files are
#                     not shipped, provide them via --model-src)
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
MODULE_ID="wall-annotation-companion"   # our own id (distinct from the archived auto-wall-companion)
# Default location the ConvNeXt-Tiny model is downloaded from when it isn't
# found locally (git-ignored, 122 MB). Override with --model-url / --model-src.
MODEL_DEFAULT_URL="http://mohammadi.eu/dateien/wall_student_convnext_tiny.onnx"

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
NO_MODULE=0; FOUNDRY_DATA=""; FOUNDRY_CONTAINER=""; MODULE_ONLY=0
DO_SERVE=0; SERVE_PORT=8178
while [ $# -gt 0 ]; do
  case "$1" in
    --port)      PORT_PREF="$2"; shift 2;;
    --host)      HOST="$2"; shift 2;;
    --threads)   THREADS="$2"; shift 2;;
    --model-src) MODEL_SRC="$2"; shift 2;;
    --model-url) MODEL_URL="$2"; shift 2;;
    --foundry-data) FOUNDRY_DATA="$2"; shift 2;;
    --docker-container) FOUNDRY_CONTAINER="$2"; shift 2;;
    --no-module|--service-only) NO_MODULE=1; shift;;
    --module-only) MODULE_ONLY=1; shift;;
    --serve-module) DO_SERVE=1; shift;;
    --serve-port) SERVE_PORT="$2"; shift 2;;
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

# ─────────────────────────────────────────────────────────────────────────────
# MULTI-STEP HANDSHAKE
# Some things genuinely cannot be done by a script: a group membership only
# applies to a NEW login session, and only you can decide to grant it. Instead
# of failing with "permission denied", such a step PAUSES: it prints exactly
# what to do, keeps every finished step recorded, and exits 4. The next
# 'bash install.sh' re-verifies everything and continues at this very point.
# ─────────────────────────────────────────────────────────────────────────────
need_user_action() {   # need_user_action <headline> [<line> ...]
  local head="$1"; shift
  printf '%s\n' "$head" > "$STATE/blocked"
  echo
  echo "${C_Y}${C_B}══════════════════════════════════════════════════════════════════════${C_0}"
  echo "${C_Y}${C_B}  ONE STEP NEEDS YOU — installation paused (nothing is broken)${C_0}"
  echo "${C_Y}${C_B}══════════════════════════════════════════════════════════════════════${C_0}"
  echo "  $head"
  echo
  local l; for l in "$@"; do echo "  $l"; done
  echo
  echo "  Everything up to here is done and remembered. Afterwards just run:"
  echo "      ${C_C}bash install.sh${C_0}          ${C_0}# continues exactly here"
  echo "  (or ${C_C}bash install.sh --module-only${C_0} to redo only this last part)"
  echo
  _log "PAUSE $head"
  exit 4
}

# ─────────────────────────────────────────────────────────────────────────────
# CONTAINER RUNTIME (Foundry in Docker/Podman is a first-class case)
# If Foundry runs in a container, its user data lives in a volume: either a
# bind mount (a host directory, usually owned by the container's Foundry uid)
# or a named volume under /var/lib/docker/volumes/... which is root-only. We
# cannot even ASK where it is without talking to the runtime socket — which
# needs membership in the 'docker' group (or sudo). That is the manual action
# the installer pauses for.
# ─────────────────────────────────────────────────────────────────────────────
CRI=""          # the usable container CLI (docker|podman), empty = none
CRI_SUDO=0      # 1 = only reachable via sudo
CRI_PRESENT=""  # runtimes that are INSTALLED (usable or not)
CRI_PROBED=0
cri_probe() {   # 0 = we can talk to a container runtime
  [ -n "$CRI" ] && return 0
  [ "$CRI_PROBED" -eq 1 ] && return 1
  CRI_PROBED=1
  local c
  for c in docker podman; do
    command -v "$c" >/dev/null 2>&1 || continue
    CRI_PRESENT="${CRI_PRESENT:+$CRI_PRESENT }$c"
    if "$c" info >/dev/null 2>&1; then CRI="$c"; CRI_SUDO=0; _log "CRI $c (direct)"; return 0; fi
    if command -v sudo >/dev/null 2>&1 && sudo -n "$c" info >/dev/null 2>&1; then
      CRI="$c"; CRI_SUDO=1; _log "CRI $c (sudo)"; return 0
    fi
  done
  return 1
}
cri() { if [ "$CRI_SUDO" -eq 1 ]; then sudo "$CRI" "$@"; else "$CRI" "$@"; fi; }
cri_label() { if [ "$CRI_SUDO" -eq 1 ]; then printf 'sudo %s' "$CRI"; else printf '%s' "${CRI:-$CRI_PRESENT}"; fi; }
cri_unlock() {  # runtime installed but not reachable: offer to use sudo for it
  [ -n "$CRI_PRESENT" ] || return 1
  [ -t 0 ] && [ -t 1 ] && command -v sudo >/dev/null 2>&1 || return 1
  echo "  ${C_B}$CRI_PRESENT is installed, but this account may not talk to it${C_0}"
  echo "  (that is a permission on the runtime socket, not a bug)."
  local a
  read -r -p "  Use sudo for the container commands now (asks your password)? [Y/n] " a
  case "${a:-y}" in
    y|Y|"") sudo -v || return 1
            local c
            for c in $CRI_PRESENT; do
              if sudo -n "$c" info >/dev/null 2>&1; then
                CRI="$c"; CRI_SUDO=1; ok "using 'sudo $c' for container access"; return 0
              fi
            done;;
  esac
  return 1
}
docker_access_gate() {   # certain: Foundry is containerized, runtime unreachable
  local rt="${CRI_PRESENT:-docker}"; rt="${rt%% *}"
  local grp="docker"; [ "$rt" = "podman" ] && grp="podman"
  need_user_action \
    "Foundry runs inside a $rt container, but this account ($(id -un)) is not allowed to talk to $rt." \
    "The module files must be placed INSIDE that container's data volume, so the" \
    "installer has to ask $rt where that volume is. Choose ONE of these:" \
    "" \
    "  ${C_B}A) give yourself $rt access — recommended, one time${C_0}" \
    "       sudo usermod -aG $grp $(id -un)" \
    "     Then ${C_B}log out and log in again${C_0} (a group change only applies to new" \
    "     sessions). In this terminal a quicker equivalent is:" \
    "       newgrp $grp" \
    "" \
    "  ${C_B}B) let the installer use sudo for the $rt commands${C_0}" \
    "       sudo -v          # type your password once, then re-run install.sh" \
    "" \
    "  ${C_B}C) skip $rt entirely and name the volume's host directory${C_0}" \
    "       bash install.sh --foundry-data /host/path/to/foundrydata" \
    "     That is the directory containing Data/ and Config/ — the host side of" \
    "     your  -v /host/path/to/foundrydata:/data  mount (see your compose file)." \
    "" \
    "  ${C_B}D) let FOUNDRY ITSELF install it — needs neither $rt nor root${C_0}" \
    "       bash install.sh --serve-module" \
    "     That serves the module over HTTP and prints a Manifest URL; you paste it" \
    "     into Foundry's ${C_B}Add-on Modules → Install Module${C_0} and Foundry (inside the" \
    "     container) downloads it into its own data folder." \
    "" \
    "  ${C_B}E) install the service only and copy the module by hand later${C_0}" \
    "       bash install.sh --no-module" \
    "     Then unzip ${MODULE_ZIP:-foundry_module/*.zip} into" \
    "       <foundrydata>/Data/modules/$MODULE_ID/"
}

# ─────────────────────────────────────────────────────────────────────────────
# LAST-RESORT ROUTE, needs neither container access nor root: let Foundry
# install the module itself. Foundry's "Install Module" takes a manifest URL,
# downloads the zip named in the manifest's `download` field and unpacks it into
# its own data folder — as the container's own user.
#   https://foundryvtt.com/article/module-development/  ("download": "A public
#   URL that provides a zip archive ... retrieved during the installation or
#   update process")
# So we serve zip + a patched manifest from the host and print the URL.
# ─────────────────────────────────────────────────────────────────────────────
host_addresses() {   # addresses a container can plausibly reach the host on
  ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1
  ip -4 -o addr show dev docker0 2>/dev/null | awk '{print $4}' | cut -d/ -f1   # bridge gateway
  ip -4 -o addr show dev podman0 2>/dev/null | awk '{print $4}' | cut -d/ -f1
}
serve_module_mode() {
  [ -f "$MODULE_ZIP" ] || die "module package missing: $MODULE_ZIP"
  local py=""
  for c in "$REPO/.venv/bin/python" python3; do
    if [ -x "$c" ] || command -v "$c" >/dev/null 2>&1; then py="$c"; break; fi
  done
  [ -n "$py" ] || die "need python3 to serve the module"

  local port="$SERVE_PORT" tries=0
  while ! port_free "$port"; do
    port=$((port+1)); tries=$((tries+1)); [ "$tries" -gt 20 ] && die "no free port near $SERVE_PORT"
  done
  local dir="$STATE/serve"; rm -rf "$dir"; mkdir -p "$dir"
  local zipname="$MODULE_ID.zip"
  cp -f "$MODULE_ZIP" "$dir/$zipname"

  # the URL Foundry must use — it is resolved INSIDE the container, so localhost
  # is wrong there; offer the host's routable addresses instead.
  local addr addrs=() a
  while IFS= read -r a; do [ -n "$a" ] && addrs+=("$a"); done < <(host_addresses)
  [ "${#addrs[@]}" -gt 0 ] || addrs=("127.0.0.1")
  addr="${addrs[0]}"
  local base="http://$addr:$port"
  zip_module_json | "$py" -c '
import json,sys
m=json.load(sys.stdin); base=sys.argv[1]; zipname=sys.argv[2]
m["download"]=f"{base}/{zipname}"        # where Foundry fetches the archive
m["manifest"]=f"{base}/module.json"      # where it looks for updates
json.dump(m,open(sys.argv[3],"w"),indent=2)
' "$base" "$zipname" "$dir/module.json" || die "could not write the patched manifest"

  step "serving the module for Foundry to install itself"
  ok "no Docker access and no root needed for this route"
  echo
  echo "  ${C_B}1.${C_0} In Foundry: ${C_B}Add-on Modules → Install Module${C_0}, paste this Manifest URL:"
  echo
  echo "        ${C_C}${C_B}$base/module.json${C_0}"
  echo
  if [ "${#addrs[@]}" -gt 1 ]; then
    echo "     If the container cannot reach that address, try one of these instead:"
    for a in "${addrs[@]:1}"; do echo "        http://$a:$port/module.json"; done
    echo "     (Docker Desktop also offers  http://host.docker.internal:$port/module.json )"
    echo
  fi
  echo "  ${C_B}2.${C_0} Click Install. Foundry downloads the zip and unpacks it into its own"
  echo "     data folder — inside the container, as the container's own user."
  echo "  ${C_B}3.${C_0} Then: Game Settings → Manage Modules → enable ${C_B}Wall Annotation Companion${C_0}."
  echo
  echo "  Waiting for Foundry to fetch it… (Ctrl-C to stop; the service install is"
  echo "  unaffected — this only serves files)"
  echo
  local log="$STATE/serve.log"; : > "$log"
  "$py" -m http.server --bind 0.0.0.0 --directory "$dir" "$port" >>"$log" 2>&1 &
  local srv=$!
  # shellcheck disable=SC2064
  trap "kill $srv 2>/dev/null" EXIT INT TERM
  local got_manifest=0 _i
  for _i in $(seq 1 3600); do          # up to 30 min
    kill -0 "$srv" 2>/dev/null || { fail "the HTTP server died — see $log"; return 1; }
    if [ "$got_manifest" -eq 0 ] && grep -q "GET /module.json" "$log" 2>/dev/null; then
      got_manifest=1; ok "Foundry fetched the manifest"
    fi
    if grep -q "GET /$zipname" "$log" 2>/dev/null; then
      ok "Foundry downloaded the module archive — installation done on its side"
      kill "$srv" 2>/dev/null
      echo
      echo "  Check ${C_B}Add-on Modules${C_0}: 'Wall Annotation Companion' $(zip_version | sed 's/.*: *//') should be listed."
      echo "  Then enable it in the world: Game Settings → Manage Modules → Save."
      echo "  (This installer cannot verify inside the container without Docker access,"
      echo "   so it trusts Foundry's own download here.)"
      return 0
    fi
    sleep 0.5
  done
  warn "nothing fetched within 30 minutes — stopping the server"
  kill "$srv" 2>/dev/null
  return 1
}

# process-list evidence, works WITHOUT any runtime access ─────────────────────
pid_in_container() { grep -qE '[:/](docker|libpod|containerd|kubepods)' "/proc/$1/cgroup" 2>/dev/null; }

# The host path of a container's volume WITHOUT asking the runtime:
# /proc/<pid>/mountinfo is world-readable even for a root-owned container
# process, and its 4th field is the source path of every mount — for a bind
# mount that IS the host directory, for a named volume it is
# /var/lib/docker/volumes/<name>/_data. Field 4 is relative to the root of the
# source filesystem, so if that filesystem is mounted elsewhere on the host we
# map it through the matching device (field 3) in our own mount table. Every
# candidate is validated later by looking for Data/ in it, so a wrong guess
# simply loses.
mount_src_candidates() {   # <maj:min> <src-root> → plausible host paths
  printf '%s\n' "$2"
  local mm root mp rel
  while read -r _ _ mm root mp _; do
    [ "$mm" = "$1" ] || continue
    [ "$root" = "/" ] && { printf '%s\n' "${mp%/}$2"; continue; }
    case "$2" in "$root"/*|"$root") rel="${2#"$root"}"; printf '%s\n' "${mp%/}/${rel#/}";; esac
  done < /proc/self/mountinfo
}
container_volume_hostpaths() {   # → host dirs that may be Foundry user data
  local pid rest mm root mp
  while read -r pid rest; do
    case "$pid" in ''|*[!0-9]*) continue;; esac
    pid_in_container "$pid" || continue
    [ -r "/proc/$pid/mountinfo" ] || continue
    while read -r _ _ mm root mp _; do
      [ -n "${mp:-}" ] || continue
      [ "$root" = "/" ] && continue          # the container's own rootfs
      case "$root" in */containers/*/hostname|*/hosts|*/resolv.conf) continue;; esac
      mount_src_candidates "$mm" "$root"
    done < "/proc/$pid/mountinfo"
  done < <(pgrep -af 'resources/app/main.js|foundryvtt|main\.mjs' 2>/dev/null)
}
FOUNDRY_PROC_MODE=""   # "" none seen | host | container
foundry_process_scan() {   # sets FOUNDRY_PROC_MODE, prints HOST-side --dataPath values
  local pid rest dp
  FOUNDRY_PROC_MODE=""
  while read -r pid rest; do
    case "$pid" in ''|*[!0-9]*) continue;; esac
    dp=$(printf '%s\n' "$rest" | grep -oE -- '--dataPath[ =][^ ]+' | head -1 | sed -E 's/--dataPath[ =]//')
    if pid_in_container "$pid"; then
      FOUNDRY_PROC_MODE="container"        # its --dataPath is a path INSIDE the container
    else
      [ -n "$FOUNDRY_PROC_MODE" ] || FOUNDRY_PROC_MODE="host"
      [ -n "$dp" ] && printf '%s\n' "${dp%/}"
    fi
  done < <(pgrep -af 'resources/app/main.js|foundryvtt|main\.mjs' 2>/dev/null)
  return 0
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
PKGS_BASE=(python gcc-libs glib2 curl unzip)    # gcc-libs/glib2: opencv wheel runtime; unzip: module.json read + extract (do_module id-guard/version-check have no fallback)
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
  # 3) download — explicit --model-url wins; otherwise the baked-in default
  #    URL (only for the ConvNeXt/onnx model; the ncnn/--vulkan model isn't hosted there).
  local url="$MODEL_URL"
  if [ -z "$url" ] && [ "$VULKAN" -eq 0 ]; then url="$MODEL_DEFAULT_URL"; fi
  if [ -n "$url" ]; then
    step "downloading model from $url"
    if command -v curl >/dev/null 2>&1; then
      curl -fL --retry 3 --max-time 1800 -o "$tgt.part" "$url"
    else
      wget -q -O "$tgt.part" "$url"
    fi
    if [ $? -eq 0 ] && mv -f "$tgt.part" "$tgt" 2>/dev/null && model_ok "$tgt"; then
      ok "downloaded $(basename "$tgt")"; return 0
    fi
    rm -f "$tgt.part"
    fail "download failed or file invalid from: $url"
    echo "    Provide it another way and re-run:  --model-src /path/to/$base" >&2
    return 1
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
Description=Wall Annotation Companion service
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

# ── step 10: install the Foundry module into the LOCAL Foundry data dir ──────
# The module (browser side) is separate from the service. On a box that runs
# Foundry locally we can install it automatically: find Foundry's user-data
# folder and drop the module into <data>/Data/modules/<id>/. Enabling it and
# picking the world stays a one-time UI click (per-world, and unsafe to poke
# while Foundry is running) — but the files land in the right place by itself.
# The module package. foundry_module/ is tracked in git (so a fresh clone has
# it); vendor/auto-wall-companion/ is git-ignored (embedded source repo) but
# present when the tree is rsync'd from a dev box. Prefer whichever exists.
module_zip_path() {
  local c
  for c in "$REPO/foundry_module/wall-annotation-companion.zip" \
           "$REPO/vendor/auto-wall-companion/module.zip"; do
    [ -f "$c" ] && { printf '%s\n' "$c"; return 0; }
  done
  return 1
}
MODULE_ZIP="$(module_zip_path || echo "$REPO/foundry_module/wall-annotation-companion.zip")"
foundry_data_candidates() {
  # print candidate USER-DATA dirs (the folder that CONTAINS Data/ and Config/)
  [ -n "$FOUNDRY_DATA" ] && printf '%s\n' "$FOUNDRY_DATA"
  # 1) a running HOST Foundry process with --dataPath=... (a containerized
  #    Foundry is skipped on purpose: its --dataPath is a path inside the
  #    container, e.g. /data, which means nothing on the host)
  foundry_process_scan
  # 2) dataPath recorded in any options.json under known config roots
  local cfg
  for cfg in "$HOME/.local/share/FoundryVTT/Config/options.json" \
             "${XDG_DATA_HOME:-$HOME/.local/share}/FoundryVTT/Config/options.json" \
             "$HOME/.config/FoundryVTT/Config/options.json" \
             /local/FoundryVTT/Config/options.json; do
    [ -f "$cfg" ] || continue
    dp=$(grep -oE '"dataPath"[^,}]*' "$cfg" | head -1 | sed -E 's/.*"dataPath" *: *"([^"]*)".*/\1/')
    [ -n "$dp" ] && printf '%s\n' "${dp%/}"
  done
  # 2b) a CONTAINERIZED Foundry's volume, read out of the container process's
  #     mount table — needs no Docker access at all (see §C.6 in the README)
  container_volume_hostpaths
  # 3) common default locations
  printf '%s\n' "$HOME/.local/share/FoundryVTT" "$HOME/FoundryVTT" \
                "$HOME/foundrydata" "$HOME/foundryuserdata" \
                "/opt/foundrydata" "/srv/foundryvtt" "/var/lib/foundryvtt"
  # 4) bounded filesystem search: a dir containing Data/modules AND Data/worlds
  local d
  while IFS= read -r d; do printf '%s\n' "$(cd "$d/../.." && pwd)"; done \
    < <(find "$HOME" -maxdepth 5 -type d -name modules -path "*/Data/modules" 2>/dev/null | head -5)
}
foundry_modules_dir() {  # echo the best candidate that looks like a real Foundry data dir
  # Two passes, because several candidates can exist (e.g. more than one
  # container with a /data volume): first insist on a dir that really looks like
  # Foundry user data (modules + worlds/systems/Config), only then fall back to
  # the loose test. Otherwise an unrelated container's volume could win.
  local c
  while IFS= read -r c; do
    [ -n "$c" ] || continue
    if [ -d "$c/Data/modules" ] && { [ -d "$c/Data/worlds" ] || [ -d "$c/Data/systems" ] || [ -d "$c/Config" ]; }; then
      printf '%s\n' "$c/Data/modules"; return 0
    fi
  done < <(foundry_data_candidates)
  while IFS= read -r c; do
    [ -n "$c" ] || continue
    if [ -d "$c/Data" ] || [ -d "$c/Data/worlds" ] || [ -d "$c/Data/systems" ]; then
      printf '%s\n' "$c/Data/modules"; return 0
    fi
  done < <(foundry_data_candidates)
  return 1
}
# reading module.json out of the zip: unzip if present, python otherwise ──────
zip_module_json() {
  if command -v unzip >/dev/null 2>&1; then
    unzip -p "$MODULE_ZIP" module.json 2>/dev/null && return 0
  fi
  local py
  for py in "$REPO/.venv/bin/python" python3 python; do
    command -v "$py" >/dev/null 2>&1 || [ -x "$py" ] || continue
    "$py" -c "import zipfile,sys; sys.stdout.write(zipfile.ZipFile(sys.argv[1]).read('module.json').decode())" \
      "$MODULE_ZIP" 2>/dev/null && return 0
  done
  return 1
}
zip_version() { zip_module_json | grep -oE '"version"[^,}]*' | head -1; }

# ── the Foundry container, if Foundry is dockerized ──────────────────────────
FCID=""; FCNAME=""; FCIMAGE=""
foundry_container_find() {   # sets FCID/FCNAME/FCIMAGE; 1 = no Foundry container
  [ -n "$FCID" ] && return 0
  cri_probe || return 1
  local line=""
  if [ -n "$FOUNDRY_CONTAINER" ]; then
    line="$(cri inspect --format '{{.Id}}|{{.Name}}|{{.Config.Image}}' "$FOUNDRY_CONTAINER" 2>/dev/null)" \
      || { fail "no container named '$FOUNDRY_CONTAINER' (checked with $(cri_label))"; return 1; }
  else
    # running containers first, then stopped ones; match image OR name
    line="$(cri ps    --format '{{.ID}}|{{.Names}}|{{.Image}}' 2>/dev/null | grep -iE 'foundry|felddy' | head -1)"
    [ -n "$line" ] || line="$(cri ps -a --format '{{.ID}}|{{.Names}}|{{.Image}}' 2>/dev/null | grep -iE 'foundry|felddy' | head -1)"
  fi
  [ -n "$line" ] || return 1
  IFS='|' read -r FCID FCNAME FCIMAGE <<<"$line"
  FCNAME="${FCNAME#/}"
  return 0
}
container_mounts() { # <cid> → "dest|src|type|name" per line
  cri inspect --format '{{range .Mounts}}{{.Destination}}|{{.Source}}|{{.Type}}|{{.Name}}{{"\n"}}{{end}}' "$1" 2>/dev/null
}
container_running() { [ "$(cri inspect --format '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]; }
container_userdata_dir() {  # <cid> → path INSIDE the container that holds Data/
  local dest src _rest
  if container_running "$1"; then
    while IFS='|' read -r dest src _rest; do
      [ -n "$dest" ] || continue
      cri exec "$1" sh -c "[ -d '${dest%/}/Data' ]" >/dev/null 2>&1 && { printf '%s\n' "${dest%/}"; return 0; }
    done < <(container_mounts "$1")
    cri exec "$1" sh -c '[ -d /data/Data ]' >/dev/null 2>&1 && { printf '/data\n'; return 0; }
    return 1
  fi
  # stopped: guess from the mount list (felddy/foundryvtt and friends use /data)
  while IFS='|' read -r dest src _rest; do
    case "${dest%/}" in */data|*/foundrydata) printf '%s\n' "${dest%/}"; return 0;; esac
  done < <(container_mounts "$1")
  return 1
}

# ── step 10: WHERE does the module have to go? ────────────────────────────────
# Three possible answers, resolved once and remembered:
#   host   — plain local Foundry: <userdata>/Data/modules on this filesystem
#   docker — Foundry in a container: into the container's data volume
#   (none) — no Foundry here: service-only install, module by hand
verify_foundry() {
  [ "$NO_MODULE" -eq 1 ] && return 0
  case "$(recall modmode)" in
    host)
      local md; md="$(recall modparent)"
      [ -n "$md" ] && [ -d "$md" ] && return 0
      fail "the recorded Foundry modules dir is gone: $md"; return 1;;
    docker)
      cri_probe || { fail "no access to the container runtime any more"; return 1; }
      foundry_container_find || { fail "the Foundry container is gone"; return 1; }
      [ -n "$(recall cdata)" ] || { fail "container data path not recorded"; return 1; }
      return 0;;
    *) fail "Foundry install location not determined yet"; return 1;;
  esac
}
do_foundry() {
  [ "$NO_MODULE" -eq 1 ] && return 0

  # (a) an explicit path always wins — no guessing, no Docker needed
  if [ -n "$FOUNDRY_DATA" ]; then
    local md="${FOUNDRY_DATA%/}/Data/modules"
    [ -d "${FOUNDRY_DATA%/}" ] || { fail "--foundry-data '$FOUNDRY_DATA' does not exist"; return 1; }
    mkdir -p "$md" 2>/dev/null || true
    [ -d "$md" ] || { fail "$md does not exist and cannot be created — is that really the user-data dir (it contains Data/ and Config/)?"; return 1; }
    remember modmode host; remember modparent "$md"; remember cdata ""; remember container ""
    ok "using --foundry-data → $md"; return 0
  fi

  # (b) a plain host installation?
  #     scan the process list HERE (not inside the candidate generator, which
  #     runs in a subshell) so FOUNDRY_PROC_MODE survives for step (c).
  foundry_process_scan >/dev/null
  local md md_ro=""; md="$(foundry_modules_dir || true)"
  if [ -n "$md" ] && [ -w "$md" ]; then
    remember modmode host; remember modparent "$md"; remember cdata ""; remember container ""
    ok "Foundry data found and writable → $md"; return 0
  fi
  if [ -n "$md" ]; then
    md_ro="$md"        # found, but owned by someone else (Foundry's own uid?)
    ok "Foundry data found → $md"
    warn "but $(id -un) may not write there — looking for a route that needs no root"
  fi

  # (c) containerized?
  local certain=0 maybe=0
  [ "$FOUNDRY_PROC_MODE" = "container" ] && certain=1
  if [ "$certain" -eq 0 ] && { command -v docker >/dev/null 2>&1 || command -v podman >/dev/null 2>&1; }; then
    maybe=1
  fi
  if [ "$certain" -eq 1 ] || [ "$maybe" -eq 1 ]; then
    [ "$certain" -eq 1 ] && ok "Foundry is running inside a container (its process is in a container cgroup)"
    if ! cri_probe; then
      cri_unlock || true
    fi
    if ! cri_probe; then
      # runtime installed but unreachable. If we already know the volume's host
      # path (read out of the container's mount table) we do not need Docker at
      # all — root can write there. Otherwise: pause with instructions.
      if [ -n "$md_ro" ]; then
        remember modmode host; remember modparent "$md_ro"; remember cdata ""; remember container ""
        warn "no Docker access — will write to $md_ro as root instead"
        warn "prefer not to use sudo? abort and run:  bash install.sh --serve-module"
        return 0
      fi
      [ "$certain" -eq 1 ] && docker_access_gate
    else
      if foundry_container_find; then
        ok "Foundry container: $FCNAME  (image $FCIMAGE)"
        # 1) is the volume's host side a directory we may WRITE? then plain file
        #    copies win — they also work while the container is stopped. If it
        #    is owned by Foundry's container uid (the usual bind-mount case) we
        #    do NOT escalate to root: copying through the runtime needs no sudo.
        local dest src _rest
        while IFS='|' read -r dest src _rest; do
          [ -n "$src" ] || continue
          if [ -d "$src/Data/modules" ] && [ -w "$src/Data/modules" ]; then
            remember modmode host; remember modparent "$src/Data/modules"
            remember cdata ""; remember container "$FCNAME"
            ok "container volume is writable on the host → $src/Data/modules"
            return 0
          fi
          [ -d "$src/Data/modules" ] && \
            ok "volume $src belongs to the container's user — installing through $(cri_label) instead"
        done < <(container_mounts "$FCID")
        # 2) named volume / not-ours path → go through the runtime itself
        local cdata; cdata="$(container_userdata_dir "$FCID" || true)"
        if [ -z "$cdata" ]; then
          fail "found container '$FCNAME' but no Foundry user data (Data/) in any of its mounts"
          warn "if that is the wrong container, name the right one:  --docker-container NAME"
          warn "or give the host path directly:  --foundry-data /path/to/foundrydata"
          return 1
        fi
        remember modmode docker; remember container "$FCNAME"
        remember cdata "$cdata"; remember modparent "$cdata/Data/modules"
        ok "will install through $(cri_label) into $FCNAME:$cdata/Data/modules"
        return 0
      fi
      [ "$certain" -eq 1 ] && {
        fail "Foundry runs in a container, but $(cri_label) lists no container matching 'foundry'"
        warn "name it explicitly:  bash install.sh --docker-container NAME"
        warn "or give the host path:  bash install.sh --foundry-data /path/to/foundrydata"
        return 1
      }
    fi
  fi

  # (d) ask
  if [ -t 0 ] && [ -t 1 ]; then
    echo "  Could not locate Foundry's user-data folder automatically."
    echo "  In Foundry it is shown at ${C_C}Setup → Configuration → \"User Data Path\"${C_0}."
    echo "  (Foundry in Docker? give the HOST directory mounted as /data — or leave"
    echo "   this blank and use  bash install.sh --serve-module  instead, which lets"
    echo "   Foundry install the module itself and needs no paths at all.)"
    local ans; read -r -p "  Paste it here (or leave blank to skip the module): " ans
    if [ -n "$ans" ]; then
      ans="${ans%/}"
      mkdir -p "$ans/Data/modules" 2>/dev/null || true
      if [ -d "$ans/Data/modules" ]; then
        remember modmode host; remember modparent "$ans/Data/modules"; remember cdata ""; remember container ""
        ok "using $ans/Data/modules"; return 0
      fi
      warn "$ans/Data/modules is not usable"
    fi
  fi

  # (e) give up on the module (the service is the critical part) — with a recipe
  warn "skipping the module install — no Foundry user-data folder found here."
  warn "do it by hand: unzip $MODULE_ZIP into <FoundryData>/Data/modules/$MODULE_ID/"
  warn "or re-run with:  bash install.sh --module-only --foundry-data /path/to/FoundryUserData"
  warn "Foundry in Docker:  bash install.sh --module-only --docker-container NAME"
  warn "no access to the container (and no root)? let Foundry install it itself:"
  warn "    bash install.sh --serve-module"
  NO_MODULE=1
  return 0
}

# ── step 11: put the module files there ──────────────────────────────────────
module_stage_tmp() {  # unpack the zip into <tmp>/<MODULE_ID>; echo <tmp>
  local t; t="$(mktemp -d "${TMPDIR:-/tmp}/wac-module.XXXXXX")" || return 1
  mkdir -p "$t/$MODULE_ID"
  if command -v unzip >/dev/null 2>&1 && unzip -oq "$MODULE_ZIP" -d "$t/$MODULE_ID"; then
    printf '%s\n' "$t"; return 0
  fi
  local py
  for py in "$REPO/.venv/bin/python" python3; do
    [ -x "$py" ] || command -v "$py" >/dev/null 2>&1 || continue
    if "$py" -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" \
         "$MODULE_ZIP" "$t/$MODULE_ID" 2>/dev/null; then printf '%s\n' "$t"; return 0; fi
  done
  rm -rf "$t"; return 1
}
module_installed_ok() {  # <moduledir> — files present and correct id+version?
  local md="$1" mj="$1/module.json"
  [ -f "$mj" ] && [ -f "$md/scripts/module.js" ] || return 1
  grep -q "\"id\": *\"$MODULE_ID\"" "$mj" || return 1
  [ "$(zip_version)" = "$(grep -oE '"version"[^,}]*' "$mj" | head -1)" ]
}
module_installed_ok_docker() {  # <cid> <module dir inside the container>
  local cid="$1" cmod="$2" mj
  container_running "$cid" || return 1      # can only read it while it runs
  mj="$(cri exec "$cid" cat "$cmod/module.json" 2>/dev/null)" || return 1
  printf '%s' "$mj" | grep -q "\"id\": *\"$MODULE_ID\"" || return 1
  cri exec "$cid" sh -c "[ -f '$cmod/scripts/module.js' ]" >/dev/null 2>&1 || return 1
  [ "$(zip_version)" = "$(printf '%s' "$mj" | grep -oE '"version"[^,}]*' | head -1)" ]
}
module_warn_siblings() {  # <modules parent dir listing command produces names>
  local other
  for other in auto-wall-companion auto-wall-companion-ml; do
    if printf '%s\n' "$1" | grep -qx "$other"; then
      warn "another module '$other' also exists there —"
      warn "disable/remove it in Foundry (Wall Annotation Companion replaces it)."
    fi
  done
}
module_install_host() {  # <modules dir>
  local moddir="$1" target="$1/$MODULE_ID" stage
  stage="$(module_stage_tmp)" || { fail "could not unpack $MODULE_ZIP"; return 1; }
  if mkdir -p "$target" 2>/dev/null && [ -w "$target" ]; then
    rm -rf "${target:?}"/* 2>/dev/null || true
    cp -a "$stage/$MODULE_ID/." "$target/" || { rm -rf "$stage"; fail "copy into $target failed"; return 1; }
  else
    # a bind-mounted container volume (or a system-wide Foundry) is typically
    # owned by Foundry's own uid → write as root, then hand the files over to
    # whoever owns the modules directory, so Foundry can still read them.
    warn "$moddir is not writable by $(id -un) — installing as root"
    warn "(no root available / rather not? abort and run: bash install.sh --serve-module)"
    run_root "create the module directory $target" mkdir -p "$target" \
      || { rm -rf "$stage"; fail "cannot create $target even as root"; return 1; }
    run_root "copy the module files into $target" cp -aT "$stage/$MODULE_ID" "$target" \
      || { rm -rf "$stage"; fail "cannot copy into $target"; return 1; }
    local own; own="$(stat -c '%u:%g' "$moddir" 2>/dev/null || true)"
    if [ -n "$own" ] && [ "$own" != "0:0" ]; then
      run_root "give the files to Foundry's user ($own)" chown -R "$own" "$target" \
        || warn "could not chown $target to $own — if Foundry cannot read the module, fix the owner"
    fi
  fi
  rm -rf "$stage"
  module_warn_siblings "$(ls -1 "$moddir" 2>/dev/null)"
  remember moduledir "$target"
  ok "module installed → $target"
}
module_install_docker() {  # <cid> <container userdata>
  local cid="$1" cdata="$2" cmods="$2/Data/modules" cmod="$2/Data/modules/$MODULE_ID" stage
  container_running "$cid" || {
    fail "container '$FCNAME' is not running — start it and re-run (files are copied through it)"
    warn "    $(cri_label) start $FCNAME"
    return 1; }
  stage="$(module_stage_tmp)" || { fail "could not unpack $MODULE_ZIP"; return 1; }
  # remove a stale copy first: 'cp' into a container MERGES directories
  cri exec -u 0 "$cid" sh -c "rm -rf '$cmod'" >/dev/null 2>&1 || true
  cri exec -u 0 "$cid" sh -c "mkdir -p '$cmods'" >/dev/null 2>&1 || true
  if ! cri cp "$stage/$MODULE_ID" "$cid:$cmods/" >>"$LOGFILE" 2>&1; then
    rm -rf "$stage"; fail "$(cri_label) cp into $FCNAME:$cmods/ failed (see $LOGFILE)"; return 1
  fi
  rm -rf "$stage"
  # files arrive owned by root; Foundry in the container runs as its own uid and
  # only needs to READ them, but match the owner of Data/modules where possible.
  local own; own="$(cri exec "$cid" stat -c '%u:%g' "$cmods" 2>/dev/null || true)"
  if [ -n "$own" ] && [ "$own" != "0:0" ]; then
    cri exec -u 0 "$cid" chown -R "$own" "$cmod" >/dev/null 2>&1 \
      && ok "files handed to Foundry's uid ($own) inside the container" \
      || warn "could not chown inside the container — module stays root-owned (readable, normally fine)"
  fi
  module_warn_siblings "$(cri exec "$cid" ls -1 "$cmods" 2>/dev/null || true)"
  remember moduledir "$cmod"
  ok "module installed → $FCNAME:$cmod"
}
verify_module() {
  [ "$NO_MODULE" -eq 1 ] && return 0
  local md; md="$(recall moduledir)"
  case "$(recall modmode)" in
    host)
      [ -n "$md" ] || { fail "Foundry module not installed yet"; return 1; }
      module_installed_ok "$md" || { fail "module files missing/outdated at $md"; return 1; };;
    docker)
      [ -n "$md" ] || { fail "Foundry module not installed in the container yet"; return 1; }
      cri_probe && foundry_container_find || { fail "cannot reach the Foundry container"; return 1; }
      if ! container_running "$FCID"; then
        warn "container '$FCNAME' is stopped — cannot re-check the module files inside it"
        marked module && return 0
        fail "module not verified (container stopped)"; return 1
      fi
      module_installed_ok_docker "$FCID" "$md" \
        || { fail "module files missing/outdated in $FCNAME:$md"; return 1; };;
    *) fail "install location unknown"; return 1;;
  esac
  return 0
}
do_module() {
  [ "$NO_MODULE" -eq 1 ] && return 0
  [ -f "$MODULE_ZIP" ] || { fail "module package missing: $MODULE_ZIP"; return 1; }
  # guard: the shipped zip MUST carry the collision-safe id
  zip_module_json | grep -q "\"id\": *\"$MODULE_ID\"" \
    || { fail "$MODULE_ZIP has the wrong module id (expected $MODULE_ID) — rebuild it from dist/"; return 1; }

  case "$(recall modmode)" in
    host)   module_install_host "$(recall modparent)" || return 1;;
    docker) foundry_container_find || { fail "Foundry container not found any more"; return 1; }
            module_install_docker "$FCID" "$(recall cdata)" || return 1;;
    *)      fail "no install location — step '${DESC[foundry]:-Foundry location}' must run first"; return 1;;
  esac

  # Foundry only rescans modules at startup.
  if [ "$(recall modmode)" = "docker" ]; then
    warn "restart the container so Foundry rescans its modules:"
    warn "    $(cri_label) restart $FCNAME"
  elif pgrep -af 'resources/app/main.js|foundryvtt|main\.mjs' >/dev/null 2>&1; then
    warn "Foundry is running — restart it so it picks up the new module."
  fi
  return 0
}

# ═════════════════════════════════════════════════════════════════════════════
# Special modes
# ═════════════════════════════════════════════════════════════════════════════
if [ "$DO_SERVE" -eq 1 ]; then
  echo "${C_B}Wall Annotation Companion — module hand-off to Foundry${C_0}"
  serve_module_mode; exit $?
fi

if [ "$DO_UNINSTALL" -eq 1 ]; then
  step "uninstalling the service"
  systemctl --user disable --now "$UNIT_NAME" 2>/dev/null && ok "unit stopped+disabled" || true
  rm -f "$UNIT_PATH" && ok "unit file removed" || true
  systemctl --user daemon-reload 2>/dev/null || true
  [ -f "$STATE/service.pid" ] && kill "$(cat "$STATE/service.pid")" 2>/dev/null && ok "background instance stopped"
  md="$(recall moduledir)"
  if [ -n "$md" ]; then
    if [ "$(recall modmode)" = "docker" ]; then
      # NEVER rm that path on the host — it is a path inside the container
      if cri_probe && foundry_container_find && container_running "$FCID"; then
        cri exec -u 0 "$FCID" sh -c "rm -rf '$md'" >/dev/null 2>&1 \
          && ok "Foundry module removed inside $FCNAME ($md)" \
          || warn "could not remove $md inside the container — do it by hand"
      else
        warn "container not reachable — remove the module by hand: $md (inside the container)"
      fi
    elif [ -d "$md" ]; then
      if [ -w "$(dirname "$md")" ]; then rm -rf "$md" && ok "Foundry module removed ($md)"
      else run_root "remove the module directory $md" rm -rf "$md" && ok "Foundry module removed ($md)"; fi
    fi
  fi
  rm -f "$STATE"/step.* "$STATE"/chosen.* "$STATE/service.pid"
  ok "state cleared (venv and model kept; delete $REPO/.venv manually if wanted)"
  exit 0
fi

ALL_STEPS=(sanity pacman model venv pydeps config unit running selftest foundry module)
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
  [foundry]="Foundry install location (local or container)"
  [module]="Foundry module files"
)
# stage 1 = the service (fully automatic) · stage 2 = the Foundry module (can
# need one manual action) · stage 3 = two clicks in Foundry's UI, by the user.
STAGE1=(sanity pacman model venv pydeps config unit running selftest)
STAGE2=(foundry module)
declare -A STAGE_OF=()
for s in "${STAGE1[@]}"; do STAGE_OF[$s]=1; done
for s in "${STAGE2[@]}"; do STAGE_OF[$s]=2; done
if [ "$MODULE_ONLY" -eq 1 ]; then
  [ "$NO_MODULE" -eq 1 ] && die "--module-only and --no-module/--service-only contradict each other"
  STEPS=("${STAGE2[@]}")
elif [ "$NO_MODULE" -eq 1 ]; then
  STEPS=("${STAGE1[@]}")
else
  STEPS=("${ALL_STEPS[@]}")
fi

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
echo "${C_B}Wall Annotation Companion — autonomous installer${C_0}"
echo "repo: $REPO    log: $LOGFILE"
[ "$VULKAN" -eq 1 ] && warn "--vulkan: MobileNetV3+ncnn GPU path (quality 0.722 vs CPU default 0.765)"

# resuming after a pause? say so, and clear the marker.
if [ -f "$STATE/blocked" ]; then
  ok "resuming after: $(head -1 "$STATE/blocked")"
  rm -f "$STATE/blocked"
fi

echo
echo "  This installation has ${C_B}3 stages${C_0}:"
echo "    ${C_B}1${C_0}  detection service         — automatic"
echo "    ${C_B}2${C_0}  Foundry module files      — automatic, unless Foundry runs in a"
echo "                                  container and this account may not use it;"
echo "                                  then it pauses and tells you what to do"
echo "    ${C_B}3${C_0}  enable it inside Foundry  — you, two clicks, once (printed at the end)"

# Heads-up BEFORE the long stage 1: if we can already see that stage 2 will
# need a manual action, say it now so it can be done in parallel.
if [ "$NO_MODULE" -eq 0 ] && [ "$MODULE_ONLY" -eq 0 ] && [ -z "$FOUNDRY_DATA" ]; then
  foundry_process_scan >/dev/null
  if [ "$FOUNDRY_PROC_MODE" = "container" ]; then
    _hu_md="$(foundry_modules_dir 2>/dev/null || true)"
    if [ -n "$_hu_md" ] && [ -w "$_hu_md" ]; then
      : # the volume is reachable and writable → stage 2 needs nothing from you
    elif ! cri_probe; then
      echo
      warn "heads-up: Foundry runs in a container here and this account can neither"
      warn "talk to the container runtime nor write to its volume — stage 2 will ask"
      warn "you to choose. You can prepare the quickest option now, in another"
      warn "terminal (saves one re-run):"
      warn "    sudo usermod -aG docker $(id -un)     # then log out and back in"
      warn "…or plan for the route that needs no privileges at all:"
      warn "    bash install.sh --serve-module        # Foundry installs it itself"
    fi
  fi
fi
echo

CUR_STAGE=""
for s in "${STEPS[@]}"; do
  if [ "${STAGE_OF[$s]:-}" != "$CUR_STAGE" ]; then
    CUR_STAGE="${STAGE_OF[$s]}"
    echo
    echo "${C_B}── stage $CUR_STAGE/3 ─────────────────────────────────────────────────${C_0}"
  fi
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
echo "  Service URL (already the module's default):   ${C_B}http://$HOST:$PORT${C_0}"
echo "  Model: $(basename "$(model_target)")   threads: $(recall threads)"
if [ "$NO_SERVICE" -eq 0 ]; then
  echo "  Service runs as a systemd user unit:"
  echo "      systemctl --user status|restart|stop $UNIT_NAME"
  echo "      journalctl --user -u $UNIT_NAME -f        # live log"
fi
echo
MD="$(recall moduledir)"
if [ -n "$MD" ] && [ "$NO_MODULE" -eq 0 ]; then
  if [ "$(recall modmode)" = "docker" ]; then
    echo "  Foundry module installed INSIDE the container $(recall container):"
    echo "      $MD"
    echo "  ${C_B}stage 3 — last one-time steps, by you:${C_0}"
    echo "    1. restart the container so Foundry rescans its modules:"
    echo "         $(cri_label) restart $(recall container)"
  else
    echo "  Foundry module installed at:"
    echo "      $MD"
    echo "  ${C_B}stage 3 — last one-time steps, by you:${C_0}"
    echo "    1. restart Foundry if it was running (so it rescans modules)"
  fi
  echo "    2. Game Settings → Manage Modules → enable ${C_B}Wall Annotation Companion${C_0} → Save"
  echo "    3. open a scene, set Scene → Configure → Padding = 0,"
  echo "       pick the Walls tool → ${C_B}Detect Walls (ML)${C_0}. Service URL is preset to the above."
  if [ "$(recall modmode)" = "docker" ]; then
    echo
    echo "  Note: the module calls the service from your ${C_B}browser${C_0}, not from inside the"
    echo "  container — http://$HOST:$PORT stays correct and you do NOT have to expose"
    echo "  the port to the container, as long as you play in a browser on this machine."
  fi
elif [ "$NO_MODULE" -eq 1 ]; then
  echo "  Foundry module: skipped (service only). Install it later with:"
  echo "      bash install.sh --module-only                       # auto-detect"
  echo "      bash install.sh --module-only --foundry-data DIR    # explicit path"
  echo "      bash install.sh --module-only --docker-container N  # Foundry in Docker"
  echo "  or by hand into  <FoundryUserData>/Data/modules/$MODULE_ID/  (README Part B)."
fi
