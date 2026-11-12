# Speech-to-text results

`scripts/asr_eval.py` writes one `<label>.md` and `<label>.json` here per run.

## Runs

| Label | Where | Result files in this repository |
| --- | --- | --- |
| `b70-whisper-turbo-real-voices` | Arc Pro B70, week of 2026-11-10 | **Not yet.** `b70-whisper-turbo-real-voices.md` and `.json` exist only on the B70 machine and have to be copied back at the next B70 session |

### b70-whisper-turbo-real-voices (placeholder until the files are fetched)

The figures below were reported from the B70 session and entered here by hand on 2026-11-12. They are not backed by a result file in this repository yet; replace this section with the real files when they are fetched, and correct anything that differs.

- Speech-to-text: whisper-large-v3-turbo served by vLLM, no prompt
- Recording: C001-S04 lines #10–#12 read aloud by two people (real voices), 23.0 s
- Character error rate: 14.1%
- Transcription time: 0.5 s
- Speaker guess: 3 of 3 segments labelled as in the script, by Qwen3-32B-AWQ, in 2.3 s

Not recorded here because it is not known without the files: the exact date, the transcript Whisper produced and where its errors were, the commit the run used, and the launcher settings (the run was made before the 2026-11-12 change that passes segments to the speaker model as JSON).

What this run is and is not: one 23-second clip of three utterances shows that the path works end to end on the card. It is not an accuracy figure for 50-minute sessions, it says nothing about overlapping speech or a quiet client, and 14.1% is above the 10% target in the README.

## Still to measure (needs the B70)

- A recording of 10 minutes or more: character error rate, real-time factor, and the time from recording to draft note.
- Speaker guessing on a full session, against the script.
