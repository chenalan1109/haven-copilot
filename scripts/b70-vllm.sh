#!/bin/bash
# Starts a vLLM server for Haven on ONE Arc Pro B70 (the final hardware is a single card).
#
#   bash scripts/b70-vllm.sh Qwen/Qwen3-8B qwen3-8b
#   bash scripts/b70-vllm.sh Qwen/Qwen3-14B qwen3-14b --quantization fp8
#   CARD=1 bash scripts/b70-vllm.sh ...        # use the second card
#
# Speech-to-text on the same card, next to the note model (both servers share the 32GB):
#   UTIL=0.7 bash scripts/b70-vllm.sh Qwen/Qwen3-32B-AWQ qwen3-32b-awq
#   PORT=8001 UTIL=0.15 CONTAINER=vllm-asr bash scripts/b70-vllm.sh openai/whisper-large-v3-turbo whisper --max-model-len 448
#
# Then: HAVEN_LLM=openai HAVEN_MODEL=qwen3-8b python3 -m haven
# The server listens on 127.0.0.1:8000 only. Model weights are cached in ~/hf.
set -e
MODEL="$1"; NAME="$2"; shift 2
CARD="${CARD:-0}"; PORT="${PORT:-8000}"; UTIL="${UTIL:-0.9}"; CONTAINER="${CONTAINER:-vllm-haven}"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
SERVE="python -m vllm.entrypoints.openai.api_server --model $MODEL --served-model-name $NAME --dtype=bfloat16 --host 127.0.0.1 --port $PORT --gpu-memory-utilization $UTIL --max-model-len 16384 --block-size 64 --trust-remote-code --enforce-eager --async-scheduling $*"
# The image needs the oneAPI runtime sourced before vLLM can see the GPU.
docker run -d --name "$CONTAINER" --net=host --ipc=host --shm-size=16g --privileged \
  --device /dev/dri:/dev/dri -v /dev/dri/by-path:/dev/dri/by-path \
  -v "$HOME/hf:/root/.cache/huggingface" \
  -e ZE_AFFINITY_MASK="$CARD" -e VLLM_WORKER_MULTIPROC_METHOD=spawn \
  -e VLLM_MAX_AUDIO_CLIP_FILESIZE_MB=200 \
  --entrypoint bash vllm/vllm-openai-xpu:v0.26.0 \
  -c "source /opt/intel/oneapi/setvars.sh --force >/dev/null 2>&1 || source /root/.bashrc 2>/dev/null; exec $SERVE"
echo "started; follow with: docker logs -f $CONTAINER"
