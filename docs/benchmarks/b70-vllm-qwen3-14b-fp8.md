# b70-vllm-qwen3-14b-fp8

- Engine: `openai-compat:qwen3-14b`
- Date: 2026-11-07T14:58:24+00:00
- Machine: Linux-7.0.0-34-generic-x86_64-with-glibc2.43
- GPU: one Intel Arc Pro B70 32GB (`ZE_AFFINITY_MASK=0`), Intel Cloud Services instance for the ASUS UGen AI League
- Server: vLLM 0.26.0 (`vllm/vllm-openai-xpu:v0.26.0`), Qwen/Qwen3-14B with online FP8 weights (`--quantization fp8`, 15.2 GiB), `--enforce-eager --max-model-len 16384`
- Output tok/s = completion tokens ÷ model time, so it includes reading the prompt.

| Session | Speech | Total | Writer | Verifier | Output tok/s | Supported |
| --- | --- | --- | --- | --- | --- | --- |
| C001-S03 | 230.0 s | 22.3 s | 19.3 s | 3.0 s | 33.6 | 10/14 |
| C001-S04 | 232.0 s | 23.9 s | 19.6 s | 4.3 s | 34.1 | 8/16 |
| C002-S05 | 110.0 s | 17.5 s | 15.2 s | 2.2 s | 34.6 | 8/13 |

**4 rooms at once:** all notes done in 24.4 s (slowest session 24.4 s), 117.5 output tokens/s in total.
