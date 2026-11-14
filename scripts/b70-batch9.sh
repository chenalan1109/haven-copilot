#!/bin/bash
# Batch 9 on ONE Arc Pro B70: every measurement the README still marks "pending",
# in one unattended run. Run it from the repository root on the B70 machine:
#
#   (nohup bash scripts/b70-batch9.sh > batch9.log 2>&1 &)          # 32B, then 8B for comparison
#   MODELS=32b bash scripts/b70-batch9.sh                           # 32B only
#   STEPS=verifier,repeat bash scripts/b70-batch9.sh                # some steps only
#
# What it does, in order (each step writes its own result files under docs/):
#   1. Starts Whisper (port 8001), waits until it answers, then the note model
#      (port 8000) with a 32k context and an fp8 context cache. If that does not
#      come up, it retries with 16k and the default cache, and says so in the summary.
#   2. Samples the card's power and memory once a second for the whole run
#      (xpu-smi if present), so peak memory and energy per session can be read off.
#   3. Steps (STEPS, default all):
#        verifier  scripts/verifier_eval.py under the current rules       -> docs/verifier-eval/
#        repeat    scripts/benchmark.py --repeat 3 (the three demo sessions) + review sheet -> docs/benchmarks/
#        long      scripts/benchmark.py --sessions C002-L50 with 1, 2 and 4 rooms at once   -> docs/benchmarks/
#   4. Writes docs/b70-batch9/<date>/summary.md: commit, model, settings actually used,
#      peak memory and mean power per step, and links to every result file.
#
# Needs: docker with vllm/vllm-openai-xpu:v0.26.0, the weights in ~/hf (the first start
# downloads them), data/sessions/C002-L50.json (in the repository). Nothing here leaves
# the machine except the first weight download from huggingface.co.
set -u
cd "$(dirname "$0")/.."
MODELS="${MODELS:-32b,8b}"
STEPS="${STEPS:-verifier,repeat,long}"
CARD="${CARD:-0}"
STAMP="$(date +%Y%m%d-%H%M)"
OUT="docs/b70-batch9/$STAMP"
mkdir -p "$OUT"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || cat SYNCED_COMMIT 2>/dev/null || echo unknown)"
SUMMARY="$OUT/summary.md"
log() { echo "[$(date +%H:%M:%S)] $*"; echo "- $(date +%H:%M:%S) $*" >> "$OUT/timeline.md"; }

wait_for() {  # port name seconds
  local port="$1" name="$2" limit="$3" t=0
  until curl -s "127.0.0.1:$port/v1/models" | grep -q "$name"; do
    sleep 5; t=$((t + 5))
    if [ "$t" -ge "$limit" ]; then return 1; fi
  done
}

# --- power and memory sampling -------------------------------------------------
MON_PID=""
start_monitor() {
  if command -v xpu-smi >/dev/null 2>&1; then
    # Metric ids as documented for xpu-smi dump: 0 utilization %, 1 power W, 18 memory used MiB.
    xpu-smi dump -d "$CARD" -m 0,1,18 -i 1 > "$OUT/monitor.csv" 2>&1 &
    MON_PID=$!
    log "monitor: xpu-smi dump on card $CARD -> $OUT/monitor.csv"
  else
    echo "xpu-smi not found; no power or memory figures" > "$OUT/monitor.csv"
    log "monitor: xpu-smi not found, power and memory are NOT recorded"
  fi
}
stop_monitor() { [ -n "$MON_PID" ] && kill "$MON_PID" 2>/dev/null; MON_PID=""; }
trap 'stop_monitor; docker rm -f vllm-haven vllm-asr >/dev/null 2>&1' EXIT

# Peak memory and mean power between two wall-clock times (HH:MM:SS) from monitor.csv.
window_stats() {
  python3 - "$OUT/monitor.csv" "$1" "$2" <<'EOF'
import csv, re, sys
path, start, end = sys.argv[1:4]
power, mem = [], []
try:
    rows = list(csv.reader(open(path)))
except OSError:
    rows = []
for r in rows[1:]:
    if len(r) < 5:
        continue
    m = re.search(r"(\d\d:\d\d:\d\d)", r[0])
    if not m or not (start <= m.group(1) <= end):
        continue
    try:
        power.append(float(r[3])); mem.append(float(r[4]))
    except ValueError:
        pass
if power:
    print(f"peak memory {max(mem) / 1024:.1f} GiB, mean power {sum(power) / len(power):.0f} W over {len(power)} s")
else:
    print("no monitor samples")
EOF
}

# --- servers ---------------------------------------------------------------------
start_servers() {  # hf-id served-name
  local hf="$1" name="$2"
  docker rm -f vllm-haven vllm-asr >/dev/null 2>&1
  log "starting Whisper"
  PORT=8001 UTIL=0.12 CONTAINER=vllm-asr bash scripts/b70-vllm.sh openai/whisper-large-v3-turbo whisper --max-model-len 448 >/dev/null
  if ! wait_for 8001 whisper 900; then log "Whisper did not come up"; docker logs --tail 40 vllm-asr > "$OUT/whisper-fail.log" 2>&1; return 1; fi
  log "starting $name: 32k context, fp8 context cache"
  CTX="32768, fp8 cache"
  UTIL=0.8 bash scripts/b70-vllm.sh "$hf" "$name" --max-model-len 32768 --kv-cache-dtype fp8 >/dev/null
  if ! wait_for 8000 "$name" 1500; then
    docker logs --tail 60 vllm-haven > "$OUT/$name-32k-fail.log" 2>&1
    log "$name did not start with 32k + fp8 (log: $OUT/$name-32k-fail.log); retrying with 16k and the default cache"
    CTX="16384, default cache (32k + fp8 failed)"
    UTIL=0.8 bash scripts/b70-vllm.sh "$hf" "$name" >/dev/null
    if ! wait_for 8000 "$name" 1500; then log "$name did not start"; docker logs --tail 60 vllm-haven > "$OUT/$name-fail.log" 2>&1; return 1; fi
  fi
  log "$name ready ($CTX)"
}

run_step() {  # label command...
  local label="$1"; shift
  local t0 t1 rc
  t0="$(date +%H:%M:%S)"; log "step $label: $*"
  "$@" > "$OUT/$label.out" 2>&1; rc=$?
  t1="$(date +%H:%M:%S)"
  log "step $label finished (exit $rc)"
  echo "| $label | $t0–$t1 | $rc | $(window_stats "$t0" "$t1") | \`$OUT/$label.out\` |" >> "$OUT/steps.md"
}

# --- run -----------------------------------------------------------------------
{
  echo "# Batch 9 on the B70: $STAMP"
  echo
  echo "- Commit: \`$COMMIT\`"
  echo "- Card: $CARD (one card only, as in the final)"
  echo "- Models: $MODELS; steps: $STEPS"
  echo "- Whisper large-v3-turbo on the same card at UTIL=0.12; note model at UTIL=0.8"
  echo
} > "$SUMMARY"
echo "| Step | Time | Exit | Card during the step | Output |" > "$OUT/steps.md"
echo "| --- | --- | --- | --- | --- |" >> "$OUT/steps.md"
start_monitor
log "idle baseline: 30 s"; T0="$(date +%H:%M:%S)"; sleep 30
echo "| idle, no servers | $T0 | – | $(window_stats "$T0" "$(date +%H:%M:%S)") | – |" >> "$OUT/steps.md"

for m in ${MODELS//,/ }; do
  case "$m" in
    32b) HF=Qwen/Qwen3-32B-AWQ; NAME=qwen3-32b-awq ;;
    8b)  HF=Qwen/Qwen3-8B;      NAME=qwen3-8b ;;
    *)   log "unknown model $m"; continue ;;
  esac
  CTX=""
  start_servers "$HF" "$NAME" || { echo "- $NAME: servers did not start, see logs in $OUT" >> "$SUMMARY"; continue; }
  echo "- $NAME context: $CTX" >> "$SUMMARY"
  T0="$(date +%H:%M:%S)"; sleep 20
  echo "| $NAME loaded, idle | $T0 | – | $(window_stats "$T0" "$(date +%H:%M:%S)") | – |" >> "$OUT/steps.md"
  export HAVEN_LLM=openai HAVEN_MODEL="$NAME" HAVEN_ASR=openai
  case ",$STEPS," in *,verifier,*) run_step "$NAME-verifier" python3 scripts/verifier_eval.py --label "b70-$NAME-$STAMP" ;; esac
  case ",$STEPS," in *,repeat,*)   run_step "$NAME-repeat3"  python3 scripts/benchmark.py --repeat 3 --label "b70-$NAME-repeat3-$STAMP" ;; esac
  case ",$STEPS," in *,long,*)
    run_step "$NAME-long-1room" python3 scripts/benchmark.py --sessions C002-L50 --label "b70-$NAME-L50-$STAMP"
    run_step "$NAME-long-2rooms" python3 scripts/benchmark.py --sessions C002-L50 --rooms 2 --label "b70-$NAME-L50-2rooms-$STAMP"
    run_step "$NAME-long-4rooms" python3 scripts/benchmark.py --sessions C002-L50 --rooms 4 --label "b70-$NAME-L50-4rooms-$STAMP"
    ;;
  esac
  docker exec vllm-haven true 2>/dev/null && docker logs --tail 30 vllm-haven > "$OUT/$NAME-server-tail.log" 2>&1
done
stop_monitor

{
  echo
  echo "## Steps"
  echo
  cat "$OUT/steps.md"
  echo
  echo "Power and memory are for the whole card while the step ran (both servers loaded). Energy per session = mean power × step time ÷ sessions."
  echo
  echo "## Result files"
  echo
  ls docs/verifier-eval/*"$STAMP"* docs/benchmarks/*"$STAMP"* 2>/dev/null | sed 's/^/- /'
  echo
  echo "## Timeline"
  echo
  cat "$OUT/timeline.md"
} >> "$SUMMARY"
log "done: $SUMMARY"
