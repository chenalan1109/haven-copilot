# Verifier test set: rules-only

- Engine: `rules + overlap (no LLM)`
- Date: 2026-11-03T09:07:45+08:00
- Cases: 48 sentences about the simulated sessions (18 correct, 30 with a known error)
- Blocked = marked unsupported, so the note cannot be signed until the therapist acts. Flagged = blocked or marked weak.

| | Blocked | Flagged |
| --- | --- | --- |
| Wrong sentences | 22/30 (73%) | 26/30 (87%) |
| Correct sentences (false alarms) | 5/18 (28%) | 13/18 (72%) |

| Error type | Blocked | Flagged |
| --- | --- | --- |
| citation: true elsewhere but cites the wrong line | 1/1 (100%) | 1/1 (100%) |
| contradiction: states the opposite of what was said (non-risk) | 3/5 (60%) | 5/5 (100%) |
| diagnosis: clinical label or diagnosis not made in the session | 2/2 (100%) | 2/2 (100%) |
| fabrication: content not in the session | 3/3 (100%) | 3/3 (100%) |
| hedge: hedged statement written as fact | 0/1 (0%) | 0/1 (0%) |
| intensity: frequency or severity overstated | 2/2 (100%) | 2/2 (100%) |
| negation: risk statement with reversed meaning | 2/3 (67%) | 3/3 (100%) |
| number: wrong number | 6/6 (100%) | 6/6 (100%) |
| pronoun: wrong gendered pronoun | 0/2 (0%) | 1/2 (50%) |
| speaker: therapist's words attributed to the client | 0/2 (0%) | 0/2 (0%) |
| time: wrong time word | 3/3 (100%) | 3/3 (100%) |

## Misses and false alarms

| Case | Type | Sentence | Status | Reason |
| --- | --- | --- | --- | --- |
| V05 | ok | 個案本週完成兩次思考紀錄，寫完較冷靜，加班太晚時則沒力氣寫。 | unsupported | 時間詞「本週」不在引用的逐字稿中 |
| V07 | ok | 本週作業：睡前十分鐘不看工作訊息，並再寫兩次與父親有關的思考紀錄。 | unsupported | 時間詞「本週」不在引用的逐字稿中 |
| V17 | speaker | 個案表示下週想練習向主管提出合理的工作量。 | supported | - |
| V18 | hedge | 個案確實什麼都做不好。 | supported | - |
| V22 | ok | 個案表示曾有結束生命的念頭，但沒有具體想怎麼做，多在夜晚獨處時出現。 | unsupported | 與引用段落的用字重疊少，請確認 |
| V23 | ok | 個案表示本週約有三、四個晚上出現該念頭。 | unsupported | 時間詞「本週」不在引用的逐字稿中 |
| V34 | pronoun | 他表示不想讓妹妹難過。 | supported | - |
| V39 | ok | 個案本週在分組報告上台，起初手抖，後段較順。 | unsupported | 時間詞「本週」不在引用的逐字稿中 |
| V47 | speaker | 個案表示焦慮會自己降下來。 | supported | - |
