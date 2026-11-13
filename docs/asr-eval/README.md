# Speech-to-text results

`scripts/asr_eval.py` writes one `<label>.md` and `<label>.json` here per run.

## Runs

| Label | Where | Result files in this repository |
| --- | --- | --- |
| `b70-whisper-turbo-real-voices` | Arc Pro B70, 2026-11-10 | [b70-whisper-turbo-real-voices.md](b70-whisper-turbo-real-voices.md) and `.json`, copied from the B70 on 2026-11-13 unchanged |

### b70-whisper-turbo-real-voices

- Speech-to-text: whisper-large-v3-turbo served by vLLM (the result file names it `openai:whisper`, the served model name), no prompt
- Recording: C001-S04 lines #10–#12 read aloud by two people (real voices), 23.0 s
- Character error rate: 14.1% against the script (85 characters). Some of the difference may be the readers' own wording (「好累喔」, 「吧」, and 「我想多了解一點」 missing); the recording was not kept, so reading slips and mishearing cannot be told apart. The result file lists both texts
- Transcription time: 0.5 s
- Speaker guess: 3 of 3 segments labelled as in the script, by Qwen3-32B-AWQ, in 2.3 s

Made with the code of commit 6cf8441, before the 2026-11-12 change that passes segments to the speaker model as JSON.

What this run is and is not: one 23-second clip of three utterances shows that the path works end to end on the card. It is not an accuracy figure for 50-minute sessions, it says nothing about overlapping speech or a quiet client, and 14.1% is above the 10% target in the README.

## Still to measure (needs the B70)

- A recording of 10 minutes or more: character error rate, real-time factor, and the time from recording to draft note.
- Speaker guessing on a full session, against the script.
