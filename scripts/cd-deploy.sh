#!/usr/bin/env bash
# Katha CI/CD — deploy on push to main, with a seatbelt.
#
# Behaviour
#   * Deploys when origin/main moves.
#   * CI gate: the pushed commit's GitHub check-runs must be GREEN. Credentials
#     are tried in order (gh CLI -> ~/katha/secrets/github_ci_token -> plain
#     curl, which works because this repo is public); with none of the three the
#     deploy proceeds with a loud WARN instead of silently shipping.
#   * Per-SHA image tag (katha:<sha>) so a deploy can be rolled back.
#   * HEALTH GATE after `up`: the container's own healthcheck plus/health.
#     Unhealthy -> AUTO-ROLLBACK to the last known-good tag.
#   * OPT-IN quiet hours: `touch ~/katha/logs/night_only` restricts deploys to
#     22:00-00:00 IST (for a period where you want the app frozen).
#
# Escape hatches
#   scripts/cd-deploy.sh --force     # hotfix: skip quiet-hours + CI gate
#   touch ~/katha/logs/cd.force      # same, for the next 5-minute tick
#
# THE ARCHIVE IS NOT IN THIS CHECKOUT (D25). The stack binds $KATHA_ARCHIVE_DIR
# and $KATHA_INDEX_DIR from server/.env — i.e. ~/katha/archive + ~/katha/index,
# outside the clone. This script refuses to deploy if those binds don't resolve,
# because a deploy that boots an empty ./archive would seed the sample story and
# look exactly like the novels were lost. There is deliberately no `down -v`.
#
# Driven by katha-cd.timer (every 5 min). Every decision lands in cd.log.
set -euo pipefail

REPO="${HOME}/Projects/katha"
COMPOSE_DIR="${REPO}/server"
APP="katha-archive"
IMAGE="katha-archive-archive:latest"          # <compose project>-<service>
HEALTH_URL="http://localhost:4901/api/health"
REPO_SLUG="JkPadarthi/katha"
ARCHIVE_DIR="${HOME}/katha/archive"
INDEX_DIR="${HOME}/katha/index"

LOG_DIR="${HOME}/katha/logs"
LOG="${LOG_DIR}/cd.log"
LOCK="${LOG_DIR}/cd.lock"
FORCE_FILE="${LOG_DIR}/cd.force"
QUIET_FILE="${LOG_DIR}/night_only"
LASTGOOD="${LOG_DIR}/last_good"
TOKEN_FILE="${HOME}/katha/secrets/github_ci_token"

log() { echo "$(date '+%F %T') $*" >> "$LOG"; }
mkdir -p "$LOG_DIR"

# --- forced (hotfix) deploy? ---
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1
[ -f "$FORCE_FILE" ] && FORCE=1

# --- optional quiet hours (opt-in; default OFF = deploy any time) ---
now_h="$(TZ=Asia/Kolkata date +%H)"
if [ "$FORCE" -eq 0 ] && [ -f "$QUIET_FILE" ] && [ "$now_h" -lt 22 ]; then
    log "skip: quiet-hours (hour=$now_h, night_only set)"; exit 0
fi

# Serialize deploys: a 5-min timer must never collide with an in-flight build.
exec 9>"$LOCK"
flock -n 9 || { log "skip: a deploy is already running"; exit 0; }

cd "$REPO"
git fetch --quiet origin main 2>>"$LOG" || true
local_sha="$(git rev-parse HEAD)"
remote_sha="$(git rev-parse origin/main)"

if [ "$local_sha" = "$remote_sha" ] && [ "$FORCE" -eq 0 ]; then
    log "up to date (${local_sha:0:7})"; rm -f "$FORCE_FILE"; exit 0
fi

if [ "$local_sha" != "$remote_sha" ]; then target_full="$remote_sha"; else target_full="$local_sha"; fi
short="${target_full:0:7}"

# --- CI gate (require green) ---
ci_conclusion() {
    local runs_json=""
    if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
        runs_json="$(gh api "repos/$REPO_SLUG/commits/$target_full/check-runs" \
            --jq '.check_runs | map({status, conclusion})' 2>/dev/null)" || true
    elif [ -f "$TOKEN_FILE" ]; then
        runs_json="$(curl -fsS -H "Authorization: token $(cat "$TOKEN_FILE")" \
            "https://api.github.com/repos/$REPO_SLUG/commits/$target_full/check-runs" 2>/dev/null \
            | python3 -c 'import sys,json;print(json.dumps(json.load(sys.stdin).get("check_runs",[])))' 2>/dev/null)" || true
    else
        # Public repo: check-runs are readable unauthenticated (rate-limited).
        runs_json="$(curl -fsS \
            "https://api.github.com/repos/$REPO_SLUG/commits/$target_full/check-runs" 2>/dev/null \
            | python3 -c 'import sys,json;print(json.dumps(json.load(sys.stdin).get("check_runs",[])))' 2>/dev/null)" || true
    fi
    if [ -z "$runs_json" ]; then echo "unknown"; return; fi
    printf '%s' "$runs_json" | python3 -c 'import sys,json
runs=json.load(sys.stdin)
print("pending" if not runs or any(r.get("status")!="completed" for r in runs)
      else ("failure" if any(r.get("conclusion") not in ("success","skipped","neutral") for r in runs)
      else "success"))'
}

if [ "$FORCE" -eq 0 ]; then
    concl="$(ci_conclusion)"
    case "$concl" in
        success) log "CI green for $short" ;;
        unknown) log "WARN: could not read check-runs for $short — deploying WITHOUT a CI gate" ;;
        *)       log "skip: CI not green for $short (=$concl)"; exit 0 ;;
    esac
fi

# NB `FORCE` is 0 or 1, and `${FORCE:+word}` is true for BOTH (it tests
# set/non-empty, not numeric) — say it explicitly instead.
if [ "$FORCE" -eq 1 ]; then
    log "FORCED deploy ${local_sha:0:7} -> $short"
else
    log "deploy ${local_sha:0:7} -> $short"
fi
git pull --ff-only --quiet origin main 2>>"$LOG" || true

# --- the novels must not be collateral: verify the binds resolve, and are not empty ---
if [ ! -d "$ARCHIVE_DIR" ] || [ -z "$(ls -A "$ARCHIVE_DIR" 2>/dev/null)" ]; then
    log "REFUSING: $ARCHIVE_DIR missing or empty — a deploy would re-seed an empty archive"
    exit 1
fi
cfg="$(cd "$COMPOSE_DIR" && docker compose config 2>>"$LOG")" || { log "REFUSING: docker compose config failed"; exit 1; }

# `docker compose config` prints volumes in the long form (type/source/target),
# NEVER as `source:target` — so pair each source with its target instead of
# grepping for a joined string that does not exist in the output. (Getting this
# wrong refuses every deploy: the guard fires on a healthy tree.)
bind_source() {
    printf '%s' "$cfg" | awk -v want="$1" '
        /^[[:space:]]*source:/ { src = $2 }
        /^[[:space:]]*target:/ { if ($2 == want) print src }'
}
check_bind() {
    local target="$1" want="$2" got
    got="$(bind_source "$target")"
    if [ "$got" != "$want" ]; then
        log "REFUSING: ${target} is bound to '${got:-nothing}', expected '${want}' (check server/.env)"
        exit 1
    fi
}
check_bind /data/archive "$ARCHIVE_DIR"
check_bind /data/index "$INDEX_DIR"

# --- build (a failed build must leave the running version untouched) ---
if ! (cd "$COMPOSE_DIR" && docker compose build archive >>"$LOG" 2>&1); then
    log "build FAILED — leaving the running version untouched"; exit 1
fi
docker tag "$IMAGE" "katha:$short" >>"$LOG" 2>&1 || true

prev=""; [ -f "$LASTGOOD" ] && prev="$(cat "$LASTGOOD")"

(cd "$COMPOSE_DIR" && docker compose up -d --force-recreate archive >>"$LOG" 2>&1)

# --- health gate (container healthcheck + the heartbeat's version) ---
st="unknown"; ver=""
for _ in $(seq 1 30); do
    sleep 3
    st="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}nohealth{{end}}' "$APP" 2>/dev/null || echo missing)"
    if [ "$st" = "healthy" ]; then
        ver="$(curl -fsS -m 5 "$HEALTH_URL" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true)"
        [ -n "$ver" ] && break
    fi
done
expect="$(python3 - "$REPO/server/app/config.py" <<'PY' 2>/dev/null || true
import re,sys
print(re.search(r'VERSION = "([^"]+)"', open(sys.argv[1]).read()).group(1))
PY
)"
if [ "$st" = "healthy" ] && { [ -z "$expect" ] || [ "$ver" = "$expect" ]; }; then
    printf '%s\n' "$short" > "$LASTGOOD"
    log "deployed $short (healthy, version=${ver:-unknown})"
else
    log "FAILED health gate for $short (state=$st version=${ver:-none} expected=${expect:-?})"
    if [ -n "$prev" ] && docker image inspect "katha:$prev" >/dev/null 2>&1; then
        log "rolling back to $prev"
        docker tag "katha:$prev" "$IMAGE" >>"$LOG" 2>&1 || true
        (cd "$COMPOSE_DIR" && docker compose up -d --force-recreate --no-build archive >>"$LOG" 2>&1) || true
        sleep 5
        rb="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}nohealth{{end}}' "$APP" 2>/dev/null || echo missing)"
        log "rollback state=$rb (tag $prev)"
    else
        log "no known-good tag to roll back to"
    fi
    exit 1
fi
rm -f "$FORCE_FILE"
