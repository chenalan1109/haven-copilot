# Batch 9 on the B70: 20261114-0742

- Commit: `9829a27`
- Card: 0 (one card only, as in the final)
- Models: 32b,8b; steps: verifier,repeat,long
- Whisper large-v3-turbo on the same card at UTIL=0.12; note model at UTIL=0.8

- qwen3-32b-awq context: 32768, fp8 cache
- qwen3-8b context: 32768, fp8 cache

## Steps

| Step | Time | Exit | Card during the step | Output |
| --- | --- | --- | --- | --- |
| idle, no servers | 07:42:01 | – | peak memory 0.0 GiB, mean power 57 W from 23 samples | – |
| qwen3-32b-awq loaded, idle | 07:46:54 | – | peak memory 30.4 GiB, mean power 57 W from 16 samples | – |
| qwen3-32b-awq-verifier | 07:47:14–07:47:26 | 0 | peak memory 30.4 GiB, mean power 233 W from 9 samples | `docs/b70-batch9/20261114-0742/qwen3-32b-awq-verifier.out` |
| qwen3-32b-awq-repeat3 | 07:47:26–07:51:16 | 0 | peak memory 30.6 GiB, mean power 229 W from 178 samples | `docs/b70-batch9/20261114-0742/qwen3-32b-awq-repeat3.out` |
| qwen3-32b-awq-long-1room | 07:51:16–07:55:21 | 0 | peak memory 30.8 GiB, mean power 230 W from 190 samples | `docs/b70-batch9/20261114-0742/qwen3-32b-awq-long-1room.out` |
| qwen3-32b-awq-long-2rooms | 07:55:21–08:03:28 | 0 | peak memory 30.8 GiB, mean power 230 W from 376 samples | `docs/b70-batch9/20261114-0742/qwen3-32b-awq-long-2rooms.out` |
| qwen3-32b-awq-long-4rooms | 08:03:28–08:11:51 | 0 | peak memory 30.8 GiB, mean power 230 W from 389 samples | `docs/b70-batch9/20261114-0742/qwen3-32b-awq-long-4rooms.out` |
| qwen3-8b loaded, idle | 08:16:10 | – | peak memory 30.6 GiB, mean power 58 W from 16 samples | – |
| qwen3-8b-verifier | 08:16:30–08:16:39 | 0 | peak memory 30.7 GiB, mean power 202 W from 7 samples | `docs/b70-batch9/20261114-0742/qwen3-8b-verifier.out` |
| qwen3-8b-repeat3 | 08:16:39–08:19:49 | 0 | peak memory 30.7 GiB, mean power 208 W from 147 samples | `docs/b70-batch9/20261114-0742/qwen3-8b-repeat3.out` |
| qwen3-8b-long-1room | 08:19:49–08:23:21 | 0 | peak memory 30.7 GiB, mean power 216 W from 165 samples | `docs/b70-batch9/20261114-0742/qwen3-8b-long-1room.out` |
| qwen3-8b-long-2rooms | 08:23:21–08:30:22 | 0 | peak memory 30.7 GiB, mean power 216 W from 326 samples | `docs/b70-batch9/20261114-0742/qwen3-8b-long-2rooms.out` |
| qwen3-8b-long-4rooms | 08:30:22–08:37:49 | 0 | peak memory 30.7 GiB, mean power 219 W from 346 samples | `docs/b70-batch9/20261114-0742/qwen3-8b-long-4rooms.out` |

Power and memory are for the whole card while the step ran (both servers loaded). Energy per session = mean power × step time ÷ sessions.

## Result files

- docs/benchmarks/b70-qwen3-32b-awq-L50-20261114-0742-review.csv
- docs/benchmarks/b70-qwen3-32b-awq-L50-20261114-0742.json
- docs/benchmarks/b70-qwen3-32b-awq-L50-20261114-0742.md
- docs/benchmarks/b70-qwen3-32b-awq-L50-2rooms-20261114-0742-review.csv
- docs/benchmarks/b70-qwen3-32b-awq-L50-2rooms-20261114-0742.json
- docs/benchmarks/b70-qwen3-32b-awq-L50-2rooms-20261114-0742.md
- docs/benchmarks/b70-qwen3-32b-awq-L50-4rooms-20261114-0742-review.csv
- docs/benchmarks/b70-qwen3-32b-awq-L50-4rooms-20261114-0742.json
- docs/benchmarks/b70-qwen3-32b-awq-L50-4rooms-20261114-0742.md
- docs/benchmarks/b70-qwen3-32b-awq-repeat3-20261114-0742-review.csv
- docs/benchmarks/b70-qwen3-32b-awq-repeat3-20261114-0742.json
- docs/benchmarks/b70-qwen3-32b-awq-repeat3-20261114-0742.md
- docs/benchmarks/b70-qwen3-8b-L50-20261114-0742-review.csv
- docs/benchmarks/b70-qwen3-8b-L50-20261114-0742.json
- docs/benchmarks/b70-qwen3-8b-L50-20261114-0742.md
- docs/benchmarks/b70-qwen3-8b-L50-2rooms-20261114-0742-review.csv
- docs/benchmarks/b70-qwen3-8b-L50-2rooms-20261114-0742.json
- docs/benchmarks/b70-qwen3-8b-L50-2rooms-20261114-0742.md
- docs/benchmarks/b70-qwen3-8b-L50-4rooms-20261114-0742-review.csv
- docs/benchmarks/b70-qwen3-8b-L50-4rooms-20261114-0742.json
- docs/benchmarks/b70-qwen3-8b-L50-4rooms-20261114-0742.md
- docs/benchmarks/b70-qwen3-8b-repeat3-20261114-0742-review.csv
- docs/benchmarks/b70-qwen3-8b-repeat3-20261114-0742.json
- docs/benchmarks/b70-qwen3-8b-repeat3-20261114-0742.md
- docs/verifier-eval/b70-qwen3-32b-awq-20261114-0742.json
- docs/verifier-eval/b70-qwen3-32b-awq-20261114-0742.md
- docs/verifier-eval/b70-qwen3-8b-20261114-0742.json
- docs/verifier-eval/b70-qwen3-8b-20261114-0742.md

## Timeline

- 07:42:01 monitor: xpu-smi dump on card 0 -> docs/b70-batch9/20261114-0742/monitor.csv
- 07:42:01 idle baseline: 30 s
- 07:42:32 starting Whisper
- 07:44:48 starting qwen3-32b-awq: 32k context, fp8 context cache
- 07:46:54 qwen3-32b-awq ready (32768, fp8 cache)
- 07:47:14 step qwen3-32b-awq-verifier: python3 scripts/verifier_eval.py --label b70-qwen3-32b-awq-20261114-0742
- 07:47:26 step qwen3-32b-awq-verifier finished (exit 0)
- 07:47:26 step qwen3-32b-awq-repeat3: python3 scripts/benchmark.py --repeat 3 --label b70-qwen3-32b-awq-repeat3-20261114-0742
- 07:51:16 step qwen3-32b-awq-repeat3 finished (exit 0)
- 07:51:16 step qwen3-32b-awq-long-1room: python3 scripts/benchmark.py --sessions C002-L50 --label b70-qwen3-32b-awq-L50-20261114-0742
- 07:55:21 step qwen3-32b-awq-long-1room finished (exit 0)
- 07:55:21 step qwen3-32b-awq-long-2rooms: python3 scripts/benchmark.py --sessions C002-L50 --rooms 2 --label b70-qwen3-32b-awq-L50-2rooms-20261114-0742
- 08:03:28 step qwen3-32b-awq-long-2rooms finished (exit 0)
- 08:03:28 step qwen3-32b-awq-long-4rooms: python3 scripts/benchmark.py --sessions C002-L50 --rooms 4 --label b70-qwen3-32b-awq-L50-4rooms-20261114-0742
- 08:11:51 step qwen3-32b-awq-long-4rooms finished (exit 0)
- 08:11:53 starting Whisper
- 08:14:09 starting qwen3-8b: 32k context, fp8 context cache
- 08:16:10 qwen3-8b ready (32768, fp8 cache)
- 08:16:30 step qwen3-8b-verifier: python3 scripts/verifier_eval.py --label b70-qwen3-8b-20261114-0742
- 08:16:39 step qwen3-8b-verifier finished (exit 0)
- 08:16:39 step qwen3-8b-repeat3: python3 scripts/benchmark.py --repeat 3 --label b70-qwen3-8b-repeat3-20261114-0742
- 08:19:49 step qwen3-8b-repeat3 finished (exit 0)
- 08:19:49 step qwen3-8b-long-1room: python3 scripts/benchmark.py --sessions C002-L50 --label b70-qwen3-8b-L50-20261114-0742
- 08:23:21 step qwen3-8b-long-1room finished (exit 0)
- 08:23:21 step qwen3-8b-long-2rooms: python3 scripts/benchmark.py --sessions C002-L50 --rooms 2 --label b70-qwen3-8b-L50-2rooms-20261114-0742
- 08:30:22 step qwen3-8b-long-2rooms finished (exit 0)
- 08:30:22 step qwen3-8b-long-4rooms: python3 scripts/benchmark.py --sessions C002-L50 --rooms 4 --label b70-qwen3-8b-L50-4rooms-20261114-0742
- 08:37:49 step qwen3-8b-long-4rooms finished (exit 0)
