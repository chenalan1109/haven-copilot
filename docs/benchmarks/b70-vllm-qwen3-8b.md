# b70-vllm-qwen3-8b

- Engine: `openai-compat:qwen3-8b`
- Date: 2026-11-07T14:50:38+00:00
- Machine: Linux-7.0.0-34-generic-x86_64-with-glibc2.43
- GPU: one Intel Arc Pro B70 32GB (`ZE_AFFINITY_MASK=0`), Intel Cloud Services instance for the ASUS UGen AI League
- Server: vLLM 0.26.0 (`vllm/vllm-openai-xpu:v0.26.0`), Qwen/Qwen3-8B bf16, `--enforce-eager --max-model-len 16384 --gpu-memory-utilization 0.9`
- Output tok/s = completion tokens ÷ model time, so it includes reading the prompt.

| Session | Speech | Total | Writer | Verifier | Output tok/s | Supported |
| --- | --- | --- | --- | --- | --- | --- |
| C001-S03 | 230.0 s | 16.6 s | 13.1 s | 3.4 s | 34.0 | 12/12 |
| C001-S04 | 232.0 s | 14.2 s | 12.1 s | 2.1 s | 34.8 | 9/11 |
| C002-S05 | 110.0 s | 11.8 s | 10.3 s | 1.5 s | 34.8 | 6/9 |

**4 rooms at once:** all notes done in 17.0 s (slowest session 17.0 s), 122.1 output tokens/s in total.
