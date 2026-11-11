# Verifier test set: rules-only

- Engine: `rules + overlap (no LLM)`
- Date: 2026-11-12T00:48:44+08:00
- Cases: 48 sentences about the simulated sessions (18 correct, 30 with a known error)
- Blocked = marked unsupported, or weak on a risk sentence, so the note cannot be signed until the therapist acts. Flagged = blocked or marked weak.

| | Blocked | Flagged |
| --- | --- | --- |
| Wrong sentences | 28/30 (93%) | 30/30 (100%) |
| Correct sentences (false alarms) | 2/18 (11%) | 13/18 (72%) |

| Error type | Blocked | Flagged |
| --- | --- | --- |
| citation: true elsewhere but cites the wrong line | 1/1 (100%) | 1/1 (100%) |
| contradiction: states the opposite of what was said (non-risk) | 3/5 (60%) | 5/5 (100%) |
| diagnosis: clinical label or diagnosis not made in the session | 2/2 (100%) | 2/2 (100%) |
| fabrication: content not in the session | 3/3 (100%) | 3/3 (100%) |
| hedge: hedged statement written as fact | 1/1 (100%) | 1/1 (100%) |
| intensity: frequency or severity overstated | 2/2 (100%) | 2/2 (100%) |
| negation: risk statement with reversed meaning | 3/3 (100%) | 3/3 (100%) |
| number: wrong number | 6/6 (100%) | 6/6 (100%) |
| pronoun: wrong gendered pronoun | 2/2 (100%) | 2/2 (100%) |
| speaker: therapist's words attributed to the client | 2/2 (100%) | 2/2 (100%) |
| time: wrong time word | 3/3 (100%) | 3/3 (100%) |

## Misses and false alarms

| Case | Type | Sentence | Status | Reason |
| --- | --- | --- | --- | --- |
| V22 | ok | 個案表示曾有結束生命的念頭，但沒有具體想怎麼做，多在夜晚獨處時出現。 | unsupported | 與引用段落的用字重疊少，請確認 |
| V39 | ok | 個案本週在分組報告上台，起初手抖，後段較順。 | unsupported | 與引用段落的用字重疊少，請確認 |
