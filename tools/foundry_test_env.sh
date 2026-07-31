#!/usr/bin/env bash
#
# foundry_test_env.sh — bring up a throwaway Foundry-in-Docker test system for
# exercising install.sh's module stage against the REAL felddy/foundryvtt image.
#
#   bash tools/foundry_test_env.sh up [--mode bind|bind-foreign|volume] [--real]
#   bash tools/foundry_test_env.sh status
#   bash tools/foundry_test_env.sh down
#
# Modes decide WHICH install.sh route gets exercised:
#   bind          host dir owned by you (felddy runs as uid 1000 'node')
#                 → install.sh finds it via /proc/<pid>/mountinfo and copies
#                   files: no Docker access, no root needed.
#   bind-foreign  host dir owned by another uid (421)
#                 → not writable → docker cp route, or sudo, or --serve-module.
#   volume        named Docker volume (host path is root-only)
#                 → docker cp route, or --serve-module.
#
# Two flavours:
#   (default) MOCK  — the real image, the real node binary and the real argv
#                     (`resources/app/main.mjs --port=… --dataPath=/data`) with a
#                     stub main.mjs. Everything the installer inspects (process
#                     cmdline, cgroup, uid, mounts, data layout) is exactly as in
#                     production; only Foundry's HTTP server is absent. Needs no
#                     Foundry licence.
#   --real          the genuine Foundry server, so the browser side (Install
#                     Module by manifest URL, enabling it, "Detect Walls (ML)")
#                     can be tested too. Foundry is licensed software, so this
#                     needs credentials. Preferred: ~/.foundry_test.json, mode
#                     600, in felddy's secrets format (never printed, and NOT
#                     visible in `docker inspect`, unlike env vars):
#                       { "foundry_username": "…", "foundry_password": "…",
#                         "foundry_license_key": "XXXXX-…" }   ← key optional
#                     Fallback: ~/.foundry_test.env with FOUNDRY_RELEASE_URL=…
#                     (timed URL from your foundryvtt.com account) or
#                     FOUNDRY_USERNAME/FOUNDRY_PASSWORD/FOUNDRY_LICENSE_KEY
#                     …or drop foundryvtt-<version>.zip into the container_cache
#                     directory printed by 'status'.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${FOUNDRY_IMAGE:-felddy/foundryvtt:release}"
NAME="${FOUNDRY_TEST_NAME:-wac-foundry-test}"
BASE="${FOUNDRY_TEST_DIR:-$HOME/.cache/wac-foundry-test}"
VOLUME="wac_foundry_test_data"
PORT=30000
MODE=bind
REAL=0
SECRETFILE="$HOME/.foundry_test.json"   # felddy /run/secrets/config.json format
ENVFILE="$HOME/.foundry_test.env"       # fallback: plain env file

C_B=$'\e[1m'; C_G=$'\e[32m'; C_Y=$'\e[33m'; C_C=$'\e[36m'; C_0=$'\e[0m'
say()  { printf '%s\n' "${C_B}==> $*${C_0}"; }
ok()   { printf '%s\n' "${C_G}  ✓ $*${C_0}"; }
warn() { printf '%s\n' "${C_Y}  ! $*${C_0}"; }
die()  { printf '%s\n' "  ✗ $*" >&2; exit 1; }

ACTION="${1:-}"; shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --mode) MODE="$2"; shift 2;;
    --real) REAL=1; shift;;
    --port) PORT="$2"; shift 2;;
    *) die "unknown option: $1";;
  esac
done
case "$MODE" in bind|bind-foreign|volume) ;; *) die "--mode must be bind|bind-foreign|volume";; esac
docker info >/dev/null 2>&1 || die "cannot talk to docker (this helper is for the DEV box, where you have access)"

DATADIR="$BASE/$MODE"

mount_arg() {
  case "$MODE" in
    volume) printf '%s' "$VOLUME:/data";;
    *)      printf '%s' "$DATADIR:/data";;
  esac
}

prepare_storage() {
  case "$MODE" in
    volume)
      docker volume create "$VOLUME" >/dev/null
      docker run --rm -u 0 -v "$VOLUME:/data" --entrypoint sh "$IMAGE" -c \
        'mkdir -p /data/Data/modules /data/Data/worlds /data/Data/systems /data/Config /data/Logs; chown -R 1000:1000 /data'
      ok "named volume $VOLUME prepared (host path is root-only by design)";;
    bind)
      mkdir -p "$DATADIR"/{Data/modules,Data/worlds,Data/systems,Config,Logs,container_cache}
      ok "bind dir $DATADIR prepared, owned by $(id -un) (uid $(id -u))";;
    bind-foreign)
      mkdir -p "$DATADIR"
      docker run --rm -u 0 -v "$DATADIR:/data" --entrypoint sh "$IMAGE" -c \
        'mkdir -p /data/Data/modules /data/Data/worlds /data/Data/systems /data/Config /data/Logs /data/container_cache; chown -R 421:421 /data'
      ok "bind dir $DATADIR prepared, owned by uid 421 (NOT writable by you)";;
  esac
}

# A process-faithful stand-in: real image, real node, the image's real argv.
MOCK_CMD='set -e
mkdir -p /data/Data/modules /data/Data/worlds /data/Data/systems /data/Config /data/Logs
[ -f /data/Config/options.json ] || printf "{\"port\":30000,\"dataPath\":\"/data\",\"hostname\":null}\n" > /data/Config/options.json
mkdir -p "$HOME/resources/app"
cat > "$HOME/resources/app/main.mjs" <<EOF
// stand-in for Foundry: keeps the process (and its argv) alive
setInterval(() => {}, 1 << 30);
EOF
cd "$HOME"
exec /usr/local/bin/node resources/app/main.mjs --port=30000 --headless --noupdate --dataPath=/data'

up() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  prepare_storage
  if [ "$REAL" -eq 1 ]; then
    local credargs=() credsrc=""
    if [ -f "$SECRETFILE" ]; then
      chmod 600 "$SECRETFILE" 2>/dev/null || true
      credargs=(-v "$SECRETFILE:/run/secrets/config.json:ro"); credsrc="$SECRETFILE (mounted as a secret)"
    elif [ -f "$ENVFILE" ]; then
      chmod 600 "$ENVFILE" 2>/dev/null || true
      credargs=(--env-file "$ENVFILE"); credsrc="$ENVFILE (env file)"
    else
      die "--real needs credentials in $SECRETFILE or $ENVFILE (see this script's header). Nothing is ever printed."
    fi
    say "starting the REAL Foundry server (credentials from $credsrc, never echoed)"
    docker run -d --name "$NAME" -p "$PORT:30000" -v "$(mount_arg)" \
      "${credargs[@]}" "$IMAGE" >/dev/null || die "docker run failed"
    local i
    for i in $(seq 1 90); do
      if curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/" 2>/dev/null; then
        ok "Foundry answers on http://127.0.0.1:$PORT/"; break
      fi
      if [ "$(docker inspect -f '{{.State.Status}}' "$NAME")" = exited ]; then
        warn "the container exited — last log lines (credentials are not logged by felddy):"
        docker logs "$NAME" 2>&1 | tail -12 | sed 's/^/      /'
        die "real Foundry did not start (missing/expired release URL, wrong credentials, or no zip in container_cache)"
      fi
      sleep 1
    done
  else
    say "starting the MOCK (real image + real node + real argv, no Foundry licence needed)"
    docker run -d --name "$NAME" -p "$PORT:30000" -v "$(mount_arg)" \
      --entrypoint sh "$IMAGE" -c "$MOCK_CMD" >/dev/null || die "docker run failed"
    sleep 2
    docker inspect -f '{{.State.Running}}' "$NAME" | grep -q true \
      || { docker logs "$NAME" 2>&1 | tail -10; die "mock container did not stay up"; }
    ok "mock Foundry process running"
  fi
  status
  echo
  say "what to run against it"
  case "$MODE" in
    bind)
      echo "  This is the no-privileges case — it must work with Docker blocked:"
      echo "    ${C_C}PATH=/tmp/nodocker:\$PATH bash install.sh --module-only${C_0}   # with a failing docker stub"
      echo "    ${C_C}bash install.sh --module-only${C_0}"
      echo "  Expect: 'Foundry data found and writable → $DATADIR/Data/modules'";;
    bind-foreign)
      echo "    ${C_C}bash install.sh --module-only${C_0}                 # → docker cp route"
      echo "    ${C_C}bash install.sh --module-only --serve-module${C_0}  # → no-privileges route"
      echo "  Expect: 'volume … belongs to the container's user — installing through docker'";;
    volume)
      echo "    ${C_C}bash install.sh --module-only${C_0}                 # → docker cp route"
      echo "    ${C_C}bash install.sh --serve-module${C_0}                # → Foundry installs it itself"
      echo "  Expect: 'will install through docker into $NAME:/data/Data/modules'";;
  esac
  [ "$REAL" -eq 1 ] && {
    echo
    echo "  Browser: ${C_B}http://127.0.0.1:$PORT/${C_0}  → accept the EULA, then"
    echo "  Add-on Modules → Install Module (paste the URL from --serve-module),"
    echo "  Manage Modules → enable Wall Annotation Companion, open a scene,"
    echo "  set Padding = 0, Walls tool → Detect Walls (ML)."
    echo "  The wall service must be running: ${C_C}bash tools/run_wall_service.sh${C_0}"
  }
}

status() {
  say "test system status"
  if docker inspect "$NAME" >/dev/null 2>&1; then
    echo "  container : $NAME  ($(docker inspect -f '{{.State.Status}}' "$NAME"), image $(docker inspect -f '{{.Config.Image}}' "$NAME"))"
    echo "  process   : $(docker inspect -f '{{.Config.Cmd}}' "$NAME")"
    echo "  volume    : $(docker inspect -f '{{range .Mounts}}{{.Type}} {{.Source}} → {{.Destination}}{{end}}' "$NAME")"
    local pid
    pid="$(docker inspect -f '{{.State.Pid}}' "$NAME" 2>/dev/null)"
    if [ "${pid:-0}" -gt 0 ]; then
      echo "  host pid  : $pid   (cgroup says container: $(grep -qE '[:/](docker|containerd)' "/proc/$pid/cgroup" 2>/dev/null && echo yes || echo no))"
      echo "  mountinfo : $(awk '$5=="/data"{print $4}' "/proc/$pid/mountinfo" 2>/dev/null | head -1)   ← what install.sh discovers without Docker"
    fi
    echo "  modules   : $(docker exec "$NAME" ls /data/Data/modules 2>/dev/null | tr '\n' ' ')"
  else
    echo "  (no container '$NAME')"
  fi
  [ -d "$BASE" ] && echo "  data dirs : $BASE/{bind,bind-foreign}   cache: $BASE/<mode>/container_cache"
  docker volume inspect "$VOLUME" >/dev/null 2>&1 && echo "  volume    : $VOLUME exists"
  return 0
}

down() {
  say "tearing the test system down"
  docker rm -f "$NAME" >/dev/null 2>&1 && ok "container removed" || true
  docker volume rm "$VOLUME" >/dev/null 2>&1 && ok "volume removed" || true
  if [ -d "$BASE" ]; then
    # bind-foreign is owned by uid 421 → remove its contents through a container
    docker run --rm -u 0 -v "$BASE:/b" --entrypoint sh "$IMAGE" -c 'rm -rf /b/bind-foreign' >/dev/null 2>&1 || true
    rm -rf "$BASE" 2>/dev/null || warn "could not remove $BASE (leftovers owned by another uid?)"
    [ -d "$BASE" ] || ok "data dirs removed ($BASE)"
  fi
}

case "$ACTION" in
  up)     up;;
  status) status;;
  down)   down;;
  *) sed -n '3,45p' "$0" | sed 's/^# \{0,1\}//'; exit 1;;
esac
