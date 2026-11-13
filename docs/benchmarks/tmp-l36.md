# tmp-l36

- Engine: `openai-compat:qwen3-32b-awq`
- Date: 2026-11-10T16:12:53+00:00
- Machine: Linux-7.0.0-34-generic-x86_64-with-glibc2.43
- Output tok/s = completion tokens ÷ model time, so it includes reading the prompt.

- Each session run 1 time(s); times and counts are medians, Supported shows the range across runs in brackets.

| Session | Speech | Total | Writer | Verifier | Output tok/s | Supported |
| --- | --- | --- | --- | --- | --- | --- |
| C002-L50 | 2181.5 s | 63.9 s | 52.0 s | 11.9 s | 21.8 | 10/25 |

Sentences the verifier did not pass: 15, listed in `tmp-l36-review.csv` for clinical review (`scripts/review_summary.py` counts real errors caught vs. correct sentences blocked).
