# Results: what has been measured, when, and what is pending

One place for every number Haven quotes. Each row names its source file. A number without a source file is not quoted anywhere else in this repository.

All sessions are scripted and simulated. "Speech" in the benchmark files is the length by the script's timestamps (110–232 s); no recording of those sessions exists.

## Definitions

- **Draft note time**: writer plus verifier, starting from a finished transcript. Speech-to-text is not included.
- **Passed the verifier** (called "Supported" in the benchmark files): the sentence was marked supported. A sentence that did not pass is either a real error or a correct sentence the verifier held back. The two have not been separated, so this is not an accuracy figure and must not be used to rank models.
- **Blocked** (verifier test set): the sentence stops signing until the therapist acts. Current meaning: unsupported, or weak and held (about risk, rejected by the model, or citing an instruction-like line). Files dated 2026-11-07 used an older meaning (unsupported only).
- **Before the fixes**: measured before the 2026-11-12 review fixes (verifier rules, risk section R, prompts as JSON). Not comparable with later runs.

## Speed and memory on one Arc Pro B70 (2026-11-07, before the fixes)

vLLM 0.26.0, note model alone on the card (`--gpu-memory-utilization 0.9`), no Whisper beside it, context 16,384 tokens, one run per session.

| Model | Weights | Draft note time, 3 sessions | 4 short sessions at once | Output tok/s | Passed the verifier | Source |
| --- | --- | --- | --- | --- | --- | --- |
| Qwen3-8B bf16 | 15.3 GiB | 16.6 / 14.2 / 11.8 s | 17.0 s | 34–35 | 12/12, 9/11, 6/9 | [b70-vllm-qwen3-8b.md](benchmarks/b70-vllm-qwen3-8b.md) (+ .json) |
| Qwen3-14B FP8 | 15.2 GiB | 22.3 / 23.9 / 17.5 s | 24.4 s | 34–35 | 10/14, 8/16, 8/13 | [b70-vllm-qwen3-14b-fp8.md](benchmarks/b70-vllm-qwen3-14b-fp8.md) (no .json) |
| Qwen3-32B AWQ 4-bit | 18.1 GiB | 29.2 / 28.5 / 19.5 s | 30.3 s | 26 | 12/13, 7/13, 2/10 | [b70-vllm-qwen3-32b-awq.md](benchmarks/b70-vllm-qwen3-32b-awq.md) (no .json) |

Known limits of these runs: single runs (a second run of C002-S05 on 32B gave 5/10); sessions of 2–4 minutes; no speech-to-text on the card; the 14B and 32B runs have no `.json`, so they cannot be re-derived from this repository.

With Whisper on the same card (from the launcher's notes, `scripts/b70-vllm.sh`): 24.5 of 30.3 GiB free after Whisper loads; the 32B model at `UTIL=0.8` gets 18.1 GiB of weights and 4.9 GiB of context cache.

## Laptop (MacBook Air M2, 8 GB, qwen2.5:7b, 2026-11-03, before the fixes)

| Draft note time, 3 sessions | 2 sessions at once | Output tok/s | Passed the verifier | Source |
| --- | --- | --- | --- | --- |
| 108.7 / 61.4 / 64.8 s | 221.7 s | 4.7–7.6 | 10/13, 6/12, 7/8 | [m2-air-openai-compat-qwen2.5-7b.md](benchmarks/m2-air-openai-compat-qwen2.5-7b.md) (+ .json) |

The README used to carry a second laptop table (63 / 44 / 37 s). No result file for that run was saved, so it has been removed.

## Verifier test set (48 team-written sentences: 30 wrong, 18 correct)

| Run | Date | Wrong blocked | Correct blocked | Meaning of "blocked", rules | Source |
| --- | --- | --- | --- | --- | --- |
| Rule layers only | 2026-11-12 | 28/30 | 2/18 | current | [rules-only.md](verifier-eval/rules-only.md) |
| Rule layers only | 2026-11-03 | 22/30 | 5/18 | old meaning, first rules | [rules-only-before-fixes.md](verifier-eval/rules-only-before-fixes.md) |
| qwen2.5:7b, laptop | 2026-11-08 | 27/30 | 1/18 | current meaning, rules before 2026-11-12 | [m2-air-ollama-qwen2.5-7b.md](verifier-eval/m2-air-ollama-qwen2.5-7b.md) |
| Qwen3-14B, B70 | 2026-11-07 | 26/30 | 0/18 | old meaning, old rules | [b70-vllm-qwen3-14b-fp8.md](verifier-eval/b70-vllm-qwen3-14b-fp8.md) (no .json) |
| Qwen3-32B, B70 | 2026-11-07 | 26/30 | 0/18 | old meaning, old rules | [b70-vllm-qwen3-32b-awq.md](verifier-eval/b70-vllm-qwen3-32b-awq.md) (no .json) |

The cases were written by the team that wrote the verifier. This is a regression check. The `rules-only` file was regenerated on 2026-11-12 under verifier rules 2026.11-4 (the rule that holds sentences citing an instruction-like line); the totals did not change.

## Risk cues (word matching, no model)

Reported by `tests/test_risk_recall.py` on every run: 64 of 64 on the reviewer's sentences, which the word lists were written from; 3 of 16 on risk sentences written afterwards; 6 of 6 everyday sentences still raise a high-level flag. No psychologist-labelled set exists.

## Speech-to-text

One clip, 23.0 s, three utterances, on the B70: character error rate 14.1%, 0.5 s to transcribe, 3 of 3 speakers guessed. The result files are not in this repository yet: see [asr-eval/README.md](asr-eval/README.md).

## Pending (needs the B70, which is available until 2026-12-02)

| Measurement | Why it matters |
| --- | --- |
| Whisper + note model on one card, 50-minute session, 1 / 2 / 4 rooms: time and peak memory; 8B against 32B; 16k against 32k context with `--kv-cache-dtype fp8` | Whether one 32 GB card holds the whole system. Nothing in this file answers that yet |
| Power draw during that load (`xpu-smi`) | Cost per session |
| Verifier test set with 14B and 32B under the current rules; `benchmark.py --repeat 3` with the flagged-sentence review sheet | Comparable figures; separates real errors from correct sentences held back |
| A recording of 10 minutes or more through Whisper | Real-time factor, error rate, recording-to-draft time |
| Packet capture with the network cable pulled | The "0 outbound connections" target |
| The launcher's new options (`OFFLINE`, `PRIVILEGED=0`, no `--trust-remote-code`) | They are untested |
| Long-session writing in parts of 60 segments, and the JSON prompt format | Only tested with a stand-in model |
