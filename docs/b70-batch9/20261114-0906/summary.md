# Batch 9 on the B70: 20261114-0906

- Commit: `1c8247a`
- Card: 0 (one card only, as in the final)
- Models: 32b; steps: verifier,repeat,long
- Whisper large-v3-turbo on the same card at UTIL=0.12; note model at UTIL=0.8

- qwen3-32b-awq context: 32768, fp8 cache

## Steps

| Step | Time | Exit | Card during the step | Output |
| --- | --- | --- | --- | --- |
| idle, no servers | 09:06:35 | – | peak memory 0.0 GiB, mean power 58 W from 23 samples | – |
| qwen3-32b-awq loaded, idle | 09:11:32 | – | peak memory 30.4 GiB, mean power 57 W from 16 samples | – |
| qwen3-32b-awq-verifier | 09:11:52–09:12:05 | 0 | peak memory 30.4 GiB, mean power 220 W from 10 samples | `docs/b70-batch9/20261114-0906/qwen3-32b-awq-verifier.out` |
| qwen3-32b-awq-repeat3 | 09:12:05–09:15:39 | 0 | peak memory 30.6 GiB, mean power 230 W from 166 samples | `docs/b70-batch9/20261114-0906/qwen3-32b-awq-repeat3.out` |
| qwen3-32b-awq-long-1room | 09:15:39–09:20:36 | 0 | peak memory 30.8 GiB, mean power 230 W from 229 samples | `docs/b70-batch9/20261114-0906/qwen3-32b-awq-long-1room.out` |
| qwen3-32b-awq-long-2rooms | 09:20:36–09:29:43 | 0 | peak memory 30.8 GiB, mean power 230 W from 423 samples | `docs/b70-batch9/20261114-0906/qwen3-32b-awq-long-2rooms.out` |
| qwen3-32b-awq-long-4rooms | 09:29:43–09:40:00 | 0 | peak memory 30.8 GiB, mean power 230 W from 478 samples | `docs/b70-batch9/20261114-0906/qwen3-32b-awq-long-4rooms.out` |

Power and memory are for the whole card while the step ran (both servers loaded). Energy per session = mean power × step time ÷ sessions.

## Result files

- docs/benchmarks/b70-qwen3-32b-awq-L50-20261114-0906-review.csv
- docs/benchmarks/b70-qwen3-32b-awq-L50-20261114-0906.json
- docs/benchmarks/b70-qwen3-32b-awq-L50-20261114-0906.md
- docs/benchmarks/b70-qwen3-32b-awq-L50-2rooms-20261114-0906-review.csv
- docs/benchmarks/b70-qwen3-32b-awq-L50-2rooms-20261114-0906.json
- docs/benchmarks/b70-qwen3-32b-awq-L50-2rooms-20261114-0906.md
- docs/benchmarks/b70-qwen3-32b-awq-L50-4rooms-20261114-0906-review.csv
- docs/benchmarks/b70-qwen3-32b-awq-L50-4rooms-20261114-0906.json
- docs/benchmarks/b70-qwen3-32b-awq-L50-4rooms-20261114-0906.md
- docs/benchmarks/b70-qwen3-32b-awq-repeat3-20261114-0906-review.csv
- docs/benchmarks/b70-qwen3-32b-awq-repeat3-20261114-0906.json
- docs/benchmarks/b70-qwen3-32b-awq-repeat3-20261114-0906.md
- docs/verifier-eval/b70-qwen3-32b-awq-20261114-0906.json
- docs/verifier-eval/b70-qwen3-32b-awq-20261114-0906.md

## Timeline

- 09:06:35 monitor: xpu-smi dump on card 0 -> docs/b70-batch9/20261114-0906/monitor.csv
- 09:06:35 idle baseline: 30 s
- 09:07:05 starting Whisper
- 09:09:21 starting qwen3-32b-awq: 32k context, fp8 context cache
- 09:11:32 qwen3-32b-awq ready (32768, fp8 cache)
- 09:11:52 step qwen3-32b-awq-verifier: python3 scripts/verifier_eval.py --label b70-qwen3-32b-awq-20261114-0906
- 09:12:05 step qwen3-32b-awq-verifier finished (exit 0)
- 09:12:05 step qwen3-32b-awq-repeat3: python3 scripts/benchmark.py --repeat 3 --label b70-qwen3-32b-awq-repeat3-20261114-0906
- 09:15:39 step qwen3-32b-awq-repeat3 finished (exit 0)
- 09:15:39 step qwen3-32b-awq-long-1room: python3 scripts/benchmark.py --sessions C002-L50 --label b70-qwen3-32b-awq-L50-20261114-0906
- 09:20:36 step qwen3-32b-awq-long-1room finished (exit 0)
- 09:20:36 step qwen3-32b-awq-long-2rooms: python3 scripts/benchmark.py --sessions C002-L50 --rooms 2 --label b70-qwen3-32b-awq-L50-2rooms-20261114-0906
- 09:29:43 step qwen3-32b-awq-long-2rooms finished (exit 0)
- 09:29:43 step qwen3-32b-awq-long-4rooms: python3 scripts/benchmark.py --sessions C002-L50 --rooms 4 --label b70-qwen3-32b-awq-L50-4rooms-20261114-0906
- 09:40:00 step qwen3-32b-awq-long-4rooms finished (exit 0)
