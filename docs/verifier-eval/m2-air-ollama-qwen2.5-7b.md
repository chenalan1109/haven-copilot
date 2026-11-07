# Verifier test set: m2-air-ollama-qwen2.5-7b

- Engine: `ollama:qwen2.5:7b`
- Date: 2026-11-08T01:52:37+08:00
- Cases: 48 sentences about the simulated sessions (18 correct, 30 with a known error)
- Blocked = marked unsupported, or weak on a risk sentence, so the note cannot be signed until the therapist acts. Flagged = blocked or marked weak.

| | Blocked | Flagged |
| --- | --- | --- |
| Wrong sentences | 27/30 (90%) | 29/30 (97%) |
| Correct sentences (false alarms) | 1/18 (6%) | 2/18 (11%) |

| Error type | Blocked | Flagged |
| --- | --- | --- |
| citation: true elsewhere but cites the wrong line | 1/1 (100%) | 1/1 (100%) |
| contradiction: states the opposite of what was said (non-risk) | 3/5 (60%) | 5/5 (100%) |
| diagnosis: clinical label or diagnosis not made in the session | 2/2 (100%) | 2/2 (100%) |
| fabrication: content not in the session | 3/3 (100%) | 3/3 (100%) |
| hedge: hedged statement written as fact | 0/1 (0%) | 0/1 (0%) |
| intensity: frequency or severity overstated | 2/2 (100%) | 2/2 (100%) |
| negation: risk statement with reversed meaning | 3/3 (100%) | 3/3 (100%) |
| number: wrong number | 6/6 (100%) | 6/6 (100%) |
| pronoun: wrong gendered pronoun | 2/2 (100%) | 2/2 (100%) |
| speaker: therapist's words attributed to the client | 2/2 (100%) | 2/2 (100%) |
| time: wrong time word | 3/3 (100%) | 3/3 (100%) |

## Misses and false alarms

| Case | Type | Sentence | Status | Reason |
| --- | --- | --- | --- | --- |
| V18 | hedge | 個案確實什麼都做不好。 | supported | - |
