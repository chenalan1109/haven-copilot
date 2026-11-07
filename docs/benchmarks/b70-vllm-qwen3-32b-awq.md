# b70-vllm-qwen3-32b-awq

- Engine: `openai-compat:qwen3-32b-awq`
- Date: 2026-11-07T15:05:57+00:00
- Machine: Linux-7.0.0-34-generic-x86_64-with-glibc2.43
- GPU: one Intel Arc Pro B70 32GB (`ZE_AFFINITY_MASK=0`), Intel Cloud Services instance for the ASUS UGen AI League
- Server: vLLM 0.26.0 (`vllm/vllm-openai-xpu:v0.26.0`), Qwen/Qwen3-32B-AWQ (4-bit weights, 18.1 GiB), `--enforce-eager --max-model-len 16384`
- Output tok/s = completion tokens ÷ model time, so it includes reading the prompt.

| Session | Speech | Total | Writer | Verifier | Output tok/s | Supported |
| --- | --- | --- | --- | --- | --- | --- |
| C001-S03 | 230.0 s | 29.2 s | 24.6 s | 4.6 s | 25.5 | 12/13 |
| C001-S04 | 232.0 s | 28.5 s | 24.4 s | 4.1 s | 25.9 | 7/13 |
| C002-S05 | 110.0 s | 19.5 s | 17.4 s | 2.1 s | 26.4 | 2/10 |

**4 rooms at once:** all notes done in 30.3 s (slowest session 30.3 s), 89.1 output tokens/s in total.

The notes vary from run to run: a second run of C002-S05 gave 5/10. Most flags were the verifier being strict (the pronoun 「他」 not in the cited line, 「下週」 for a plan the client stated without a time word), and one was a verifier bug fixed after this run: 「讀書計畫」 was treated as a risk "plan" (see tests/test_agents.py).
