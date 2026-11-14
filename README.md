# Haven 心港 — an on-premises AI copilot for psychotherapists

**ASUS UGen AI League Hackathon · Workplace AI · Battlefield Thunderstorm (ASUS UGen Intel Arc Pro B70 32GB)**

Haven turns a therapy session into a draft progress note, risk cues and outcome-tracking reminders. By default everything runs on one machine in the clinic: Haven's own code sends session content only to a model server on the same machine (or, if configured, to a named server on the clinic's private network), and it calls no cloud service. Therapists get AI documentation help without handing their clients' most sensitive data to a third-party processor.

What this does and does not claim is spelled out under "Privacy and safety guards in the code" and "Limitations". In short: the address check covers Haven's own requests, not what a model server does afterwards; a network capture during a session has not been done yet; and data on disk is not encrypted yet.

> All data in this repository is **scripted, simulated sessions** written by the team. No real client information. The transcripts are scripts, not recordings: only a 23-second excerpt (C001-S04, lines #10–#12) was read aloud by two people, for the speech-to-text test. The "Speech" column in the benchmark files is the length given by the script's timestamps, not the length of a recording.

## Why on-device

- **Privacy is the product.** In Taiwan, health and medical data is a special category of personal data under the Personal Data Protection Act (Art. 6). That does not forbid cloud tools; it means a clinic that uses one takes on a third-party processor, usually abroad, for its most sensitive records, and a small practice has no legal staff to assess that. The AI note tools we know of for therapists are cloud services:

  | Product | Where it runs |
  | --- | --- |
  | Upheal | Vendor's cloud |
  | Mentalyc | Vendor's cloud |
  | Eleos Health | Vendor's cloud |
  | Blueprint | Vendor's cloud |
  | **Haven** | A machine in the clinic |

  This is our reading of each vendor's public site in October 2026 and has not been checked with the vendors.
- **The record has to last.** The Psychologists Act (Art. 25) requires practice records to be kept for at least 10 years. Notes that are wrong or invented stay wrong for a decade, so every sentence must be traceable.
- **One card has to hold the whole system.** The case for a 32 GB card is not that a bigger model writes better notes: on our three short sessions the 8B model was faster than the 32B one and had more sentences pass the verifier (see [docs/RESULTS.md](docs/RESULTS.md)), and that count does not measure note quality either way. The case is that speech-to-text, the note model and the context of several 50-minute sessions must sit on one card at the same time. **That has not been measured yet.** What is measured: Whisper and Qwen3-32B (4-bit) load together on one B70, and with both loaded about 4.9 GiB is left for the note model's context. Whether that is enough for one 50-minute session, let alone four rooms at once, is the open question; the measurement (peak memory and time for 1, 2 and 4 rooms, 8B against 32B, 16k against 32k context) is planned on the B70 and its numbers are pending.

## How it works

```mermaid
flowchart LR
    A[Session audio<br/>with client consent] --> ASR[ASR agent<br/>Whisper, timestamps]
    ASR --> SPK[Speaker agent<br/>guesses therapist / client<br/>from the words]
    Q[Waiting-room questionnaires<br/>BSRS-5, PHQ-9, GAD-7] --> O
    SPK --> ORCH[Orchestrator]
    ORCH --> W[Note-writer agent<br/>SOAP / DAP + R]
    W --> V[Verifier agent<br/>every sentence vs. transcript]
    ORCH --> R[Risk agent<br/>cues + exact quotes<br/>rules only, no model]
    ORCH --> O[Outcome agent<br/>reliable change, not-on-track]
    V --> DB[(Local SQLite<br/>drafts, signed notes,<br/>hash-chained audit log)]
    O --> DB
    DB --> MEM[Case memory<br/>keyword search, one client]
    ORCH <--> UI[Therapist UI<br/>review, edit, sign]
    UI --> SIGN[Signing gate on the server<br/>re-verifies, checks risk cues]
    SIGN --> DB
```

Haven makes no request to a cloud service. Where each part runs on the Stage II hardware:

```mermaid
flowchart TB
    subgraph PC[One ASUS UGen workstation in the clinic]
        subgraph GPU[Intel Arc Pro B70, 32 GB: 30.3 GiB usable]
            WH[vLLM container, 127.0.0.1:8001<br/>whisper-large-v3-turbo<br/>UTIL 0.12]
            LLM[vLLM container, 127.0.0.1:8000<br/>Qwen3-32B-AWQ, 4-bit<br/>UTIL 0.8: 18.1 GiB weights + 4.9 GiB context]
        end
        subgraph CPU[CPU]
            HV[Haven, Python standard library, 127.0.0.1:8765<br/>orchestrator, risk, outcome, verifier rules,<br/>signing gate, SQLite]
            BR[Browser: therapist UI]
        end
        BR <--> HV
        HV -- audio, OpenAI transcription API --> WH
        HV -- prompts, OpenAI chat API --> LLM
    end
```

The memory figures are from the launcher's measured notes (`scripts/b70-vllm.sh`): with Whisper loaded, 24.5 of 30.3 GiB are free, and the note model at `UTIL=0.8` gets 18.1 GiB of weights and 4.9 GiB of context cache. Peak memory under load and power draw have not been measured. On a laptop the same code runs with Ollama or with no model at all, and Whisper runs in-process on the CPU.

**Models**

| Role | Model | Size and form | Memory for weights (measured) | Context in the launcher | Licence (per model card; check before release) |
| --- | --- | --- | --- | --- | --- |
| Notes, verifier check, speaker guess (B70) | [Qwen/Qwen3-32B-AWQ](https://huggingface.co/Qwen/Qwen3-32B-AWQ) | 32B, 4-bit AWQ | 18.1 GiB | 16,384 tokens | Apache-2.0 |
| Alternative measured on the B70 | Qwen/Qwen3-14B | 14B, FP8 at load | 15.2 GiB | 16,384 | Apache-2.0 |
| Alternative measured on the B70 | Qwen/Qwen3-8B | 8B, bf16 | 15.3 GiB | 16,384 | Apache-2.0 |
| Speech-to-text (B70) | openai/whisper-large-v3-turbo | 809M | about 1.6 GB download; memory on the card not measured separately | 448 | MIT |
| Notes on a laptop | qwen2.5:7b through Ollama | 7B, Ollama's default 4-bit | not measured | Ollama default | Apache-2.0 |
| Speech-to-text on a laptop | faster-whisper `small` | int8, CPU | not measured | – | MIT |

Served by vLLM 0.26.0 (`vllm/vllm-openai-xpu:v0.26.0`). The 16,384-token context is too small for a 50-minute session in one request, which is why the writer works in parts of 60 segments; a 32k setting is part of the pending B70 measurement.

| Agent | What it does | Where |
| --- | --- | --- |
| ASR | Speech to timestamped segments. On the B70: whisper-large-v3-turbo served by vLLM through the OpenAI transcription API (`HAVEN_ASR=openai`). On a laptop: faster-whisper, int8, in-process | `haven/transcript.py` |
| Speaker | Whisper gives no speakers, so the local LLM labels each segment therapist or client from its words. The labels are guesses, shown as 「（推測）」, and the risk agent and verifier treat them with care. The therapist corrects them line by line against the recording and presses 確認說話者; confirmed labels (✓) count like a prepared transcript, and the risk scan, checklist and every sentence are checked again. No acoustic diarization | `haven/agents/speakers.py` |
| Note writer | Drafts SOAP or DAP notes; every sentence cites segment ids. Both templates end with a risk section, R (風險與安全), with no sentence limit: a transcript line with a high-level risk cue that no sentence cites is added there as a quote, whichever engine wrote the note. The objective section is for the clinician's observations of behaviour and affect in the session, still cited; what a transcript cannot show (appearance, affect, orientation) the therapist adds. Sessions over 60 segments are written in parts of 60 and joined | `haven/agents/writer.py` |
| Verifier | Checks each sentence against the segments it cites, in three layers: hard rules (numbers, time words and gendered pronouns must appear in the cited lines; a risk or behaviour word such as 想死, 割腕, 安眠藥 or 打 must be denied or stated as in the cited lines, with a double negation such as 「沒有一天不想死」 read as stated; a client's hedged self-criticism must not be written as fact), word overlap for the sentence and for each clause (a clause with no counterpart in the cited lines holds the sentence), then one batched local-LLM check for paraphrases. Signing is blocked until the therapist edits, deletes or confirms every unsupported sentence, every weak sentence about risk (suicide, self-harm, harm to others, abuse or substance wording, or a sentence citing a line with a risk cue), and every weak sentence the local model was asked about and rejected. If the model does not answer, the sentence says so (「本機模型未回應」) instead of reporting a model judgement | `haven/agents/verifier.py` |
| Risk | Keyword and pattern matching, the same in every mode (no model is involved). Flags cues with the exact quote: suicidal ideation (direct, indirect and Taiwanese-language wording), preparation, plans or means, suicidal behaviour and past attempts, self-harm, harm to others including taking a child along, substance use, functioning, and **mandated-reporting cues** (family violence, child protection, elder or disability protection, sexual assault). A reporting cue names the law and asks the therapist to assess whether to report; Haven never reports anything itself. Negated cues are kept for review, a double negation is not lowered, another person's suicide is shown as background (not the client's ideation), and a therapist's restatement of a disclosure is scanned too. **The cue lists were widened from a reviewer's list on 2026-11-12 and are 待心理師確認: not yet checked by a licensed psychologist.** When suicide cues appear, shows which parts of a risk inquiry the session covered (ideation, frequency, plan, intent, access to means, past attempts, protective factors, safety plan, crisis resources) and which to consider asking or documenting | `haven/agents/risk.py` |
| Outcome | Routine outcome monitoring: reliable change (PHQ-9: 6, GAD-7: 4), also between the last two sessions; clinically significant change; a not-on-track rule (from the third score on: still in the clinical range and not reliably improved since the first) with a review prompt; reminders, not "deteriorated" alerts, for the two single suicide items (PHQ-9 item 9 and BSRS-5 item 6, both from a score of 1, the BSRS-5 item adding referral advice from 2). BSRS-5 has no published reliable-change value, so 3 points is used and marked 暫定. Writes the score lines into the note's objective section | `haven/agents/outcome.py` |
| Case memory | Keyword search over that client's own sessions only. "哪幾次提到父親？" is widened to the words clients use (爸爸, 我爸…), every session is searched, and the answer lists how many lines matched in each session with up to three shown per session. Risk topics (自殺, 想死, 自傷, 保護因子…) are widened too. A speaker shown as unknown or guessed stays that way. No match means the words did not match, and the page says so; it is not evidence the topic never came up. The word families are 待心理師確認 | `haven/agents/memory.py` |
| Orchestrator | Runs the agents, times each one, stores the result and writes the audit log | `haven/orchestrator.py` |
| Signing gate | Not an agent: the server-side check that decides whether a note can be signed (see below) | `haven/signing.py` |

**Human in the loop:** Haven only produces drafts and prompts. A note is filed only after the therapist reviews and signs it. Haven does not diagnose or give any output to the client, and it does not analyse facial expressions.

**Privacy and safety guards in the code** (tested in `tests/`):
- **Haven's own requests go to local addresses only.** The model and transcription endpoints must be `http` or `https` to loopback or a private LAN address. A name (`localhost`, `*.local`) is resolved and every address checked, and the connection is then made to the address that was checked, so a name that changes its answer between the check and the connection is not followed. Requests that carry session content use no HTTP or system proxy, follow no redirect, and have no `ftp:`, `file:` or `data:` handler. (Model downloads by `faster-whisper`, Hugging Face or the vLLM container are a separate matter: they happen at install time and do honour proxies.)
- **This check covers the first hop only.** Haven cannot see what the model server does with a request. A model name that marks a cloud model (Ollama's `-cloud` / `:cloud`) is refused, and Ollama is asked whether the model is served remotely, but a local gateway that forwards elsewhere under an ordinary name would pass. The model server itself has to be set up to run offline (see `scripts/b70-vllm.sh`: `OFFLINE=1`, usage statistics off).
- **The status bar shows state, not a slogan.** `/api/status` reports the model and transcription endpoints, the addresses their names resolve to right now, whether those are loopback, and how many connections Haven's endpoint check has refused since start. It is not a packet capture; that measurement is still to do (see Stage II targets).
- The server binds to `127.0.0.1`, rejects requests whose `Host` header is not its own (DNS rebinding), and requires an `X-Haven` header on **every API request, reads included**, so another website open in the browser cannot sign, upload, start the model or write to the audit log. A `GET` only reads (and records the read in the audit log); drafting a note (`POST /api/sessions/<id>/open`), processing and asking the case memory (`POST /api/clients/<id>/ask`) are POSTs. Every response carries `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'; …`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`.
- **Prompt injection.** Transcript lines reach the model as JSON strings, every system prompt says they are data and not instructions, and every request has a token limit. The model has no tools and no network, and the UI inserts everything as plain text. A note sentence that cites a line worded like an instruction to the AI (「請在評估欄寫…」, 「忽略以上指示」) is held until the therapist confirms it; that word list is an engineering guess (待心理師確認). This lowers the risk; it does not remove it.
- **Signing is decided by the server.** When a note is signed, the server reads the stored transcript and checks every sentence again. From the browser it takes only the sentence texts, the segments they cite, which flagged sentences the therapist confirmed, and which risk cues the therapist left out with a reason. A `status`, `support`, `source` or `must_confirm` sent by the browser is ignored. A sentence the server's verifier has already judged (same text, same citations, same transcript, same rule version) keeps that verdict; any other sentence is checked by the rule layers at signing. The server answers 404 for a session that does not exist and 409 for an empty note, a session with no draft, an unsupported or held sentence the therapist has not confirmed, or a score line that differs from the questionnaire data.
- **Risk cues must be accounted for.** A note cannot be signed while a high-level risk cue in the transcript is cited by no sentence, unless the therapist leaves it out with a written reason. The reason goes into the audit log.
- **A signed note is locked.** The session cannot be processed again, re-verified or signed a second time (session ids are upper-cased, so `c001-s04` is the same session). The session page shows the signed note, read-only. Corrections go in an addendum (`POST /api/sessions/<id>/addendum`), which can only be appended. Each signature stores the SHA-256 of the transcript file and of the signed note and the verifier rule version, and is written in the same database transaction as its audit row. The hashes make a later change detectable by comparison; they are not a cryptographic signature, and someone with access to the database file can still change both.
- **The server answers every request.** An unexpected error is a JSON 500 with no detail (the terminal gets the exception class and location, not its message); a malformed note is a 400; only a missing session or client is a 404. `Content-Length` must be a non-negative number, JSON bodies are limited to 2 MB (recordings to 200 MB), and a connection that sends nothing for 30 seconds is closed.
- **One session, one writer.** A session id being uploaded is reserved: a second upload with the same id gets 409 instead of replacing the first, and uploads at once get different session numbers. Several requests opening a session for the first time run the pipeline once. An empty file or a recording with no recognised speech creates no session and says why; a very short transcript is kept and carries a warning.
- Uploads require a ticked consent box (the therapist's statement that written consent was obtained; Haven does not hold the consent form). **Haven keeps no recording**: the audio is written to a 0600 temporary file inside the data directory, sent to the local transcription server, and removed when transcription ends, on success and on every failure path; anything a crash leaves there is removed at the next start. Removal is an ordinary delete, not a secure erase, so use full-disk encryption. An upload is treated as a real client unless `simulated=1` is sent, and its id must start with the client id.
- **Files are for this account only, and not encrypted.** The data directory is 0700 and the database, transcripts and client file 0600. `.gitignore` covers everything Haven writes (only the three simulated demo transcripts are tracked), and `scripts/pre_commit_check.py` is an example Git hook that refuses a staged database, recording, or transcript not marked `"simulated": true`. Note that `data/clients.json` is tracked and an upload adds the new session id to it. There is no encryption at rest yet (SQLCipher is planned, not built).
- Questionnaire scores enter the note from the score data, not from the model. Score lines cannot be edited in the UI, and the server accepts a sentence as a score line only when its text equals the line it builds from the questionnaire data; an edited one is marked unsupported and cannot be signed as a score line.
- **Audit log.** Processing, re-verification, case-memory questions, signing, addenda, uploads (failed ones too) and reads of a session, a brief, the client list or the log itself are written to a local audit log with the session or client id, never the content. There are no accounts, so a row does not say who acted. Each row stores the hash of the row before it: `GET /api/audit/verify` or `python3 scripts/verify_audit.py` reports the first row that was changed, inserted or deleted. Someone who can write the database file can still rebuild the whole chain or cut rows off its end; comparing the head hash with a copy kept elsewhere detects that. Haven does not keep such a copy for you.

## Quick start (laptop, no GPU needed)

Requires Python 3.10+. The core has no third-party dependencies.

```bash
python3 scripts/reset_demo.py   # a clean, unsigned demo state (see "Demo walkthrough")
python3 -m haven
```

Open http://127.0.0.1:8765. Without a local model, Haven uses its **rule-based demo engine**, which selects what was said and changes only the speaker (「我」 to 「個案」), so the notes read like quotes. A proposal such as 「我們來擬安全計畫，好嗎？」 is written as 「心理師提議…（個案回應：…）」, not as a finished plan.

If a local model is configured but does not answer, the same rule engine writes the draft and the result says so: the engine label reads 「規則引擎（本機模型未回應）」, the session page shows a red banner, and the audit log records it.

### With a local LLM (recommended for the demo)

Install [Ollama](https://ollama.com), then:

```bash
ollama pull qwen2.5:7b
HAVEN_LLM=ollama HAVEN_MODEL=qwen2.5:7b python3 -m haven
```

Any server with Ollama's `/api/chat` API on the local machine or LAN works (`HAVEN_LLM_URL`).

Generating a note takes about a minute on a laptop, so process the demo sessions before recording:

```bash
python3 scripts/prepare_demo.py
```

On a MacBook Air M2 (8 GB) with qwen2.5:7b a note for one of the short demo sessions took 61–109 s ([docs/benchmarks/m2-air-openai-compat-qwen2.5-7b.md](docs/benchmarks/m2-air-openai-compat-qwen2.5-7b.md), 2026-11-03). An earlier table here gave 37–63 s from a run whose result file was never saved; it has been removed. What the verifier caught in those laptop runs: "下週五" where the session said "這週五", "近兩週" attached to a statement that had no time frame, and feelings ("自責") the cited line did not contain. It also flags some correct paraphrases; the therapist clears those with 「保留此句（我已核對）」. A 7B model on a laptop is the floor.

### On the Arc Pro B70 (Stage II)

The B70 runs models through vLLM (XPU), llama.cpp (SYCL) or OpenVINO Model Server. All three serve the OpenAI chat API, so Haven talks to them the same way:

```bash
HAVEN_LLM=openai HAVEN_LLM_URL=http://127.0.0.1:8000 HAVEN_MODEL=<served model name> python3 -m haven
```

The endpoint check still applies: only this machine or the clinic LAN is accepted (loopback, 10/8, 172.16/12, 192.168/16, fc00::/7; a `.local` name must resolve to one of them). Redirects are not followed. A private address is not proof of a clinic LAN (VPNs and public Wi-Fi use the same ranges), and the connection to a LAN server is plain HTTP unless you configure `https`; the supported setup is a model server on the same machine.

On a B70 with Docker, `scripts/b70-vllm.sh` starts vLLM on one card, listening on 127.0.0.1 only:

```bash
bash scripts/b70-vllm.sh Qwen/Qwen3-32B-AWQ qwen3-32b-awq
HAVEN_LLM=openai HAVEN_MODEL=qwen3-32b-awq python3 -m haven
```

**Measured on one Arc Pro B70 32GB** on 2026-11-07 (vLLM 0.26.0; the three scripted sessions, 110–232 s of speech by the script's timestamps; one run each; note model alone on the card, `UTIL=0.9`, no Whisper beside it):

| Model on one card | Memory for weights | Draft note per session | 4 short sessions at once | Output tok/s | Sentences that passed the verifier |
| --- | --- | --- | --- | --- | --- |
| Qwen3-8B, bf16 | 15.3 GiB | 11.8–16.6 s | 17.0 s | 34 | 27 of 32 |
| Qwen3-14B, FP8 | 15.2 GiB | 17.5–23.9 s | 24.4 s | 34 | 26 of 43 |
| Qwen3-32B, 4-bit AWQ | 18.1 GiB | 19.5–29.2 s | 30.3 s | 26 | 21 of 36 |

Read this table for speed and memory only.

- **The times are for the note and the verifier check, starting from a finished transcript.** Speech-to-text is not included, and the sessions are 2–4 minutes long, not 50.
- **"4 at once" was measured without Whisper on the card.** With Whisper loaded the note model has 4.9 GiB for context, and four 50-minute sessions at once have not been tried.
- **"Passed the verifier" is not accuracy.** A sentence that did not pass may be a real error or a correct paraphrase the verifier held back; the two have not been separated yet (a clinician's reading of the flagged sentences is planned). Notes also vary between runs: a second run of C002-S05 on the 32B model gave 5 of 10 instead of 2 of 10. These runs predate the 2026-11-12 fixes (verifier rules, the risk section, prompts as JSON), so the counts will change when re-run.
- Source files: [docs/benchmarks](docs/benchmarks). All figures, definitions and what is still pending are collected in [docs/RESULTS.md](docs/RESULTS.md).

### Measuring performance

```bash
python3 scripts/benchmark.py --rooms 4
```

Processes every demo session, then four at once (four therapy rooms), and writes per-agent times, token counts and tokens per second to `docs/benchmarks/`. It uses a throwaway database. Results so far are in [docs/benchmarks](docs/benchmarks).

```bash
python3 scripts/benchmark.py --repeat 3 --rooms 4
python3 scripts/review_summary.py docs/benchmarks/<label>-review.csv
```

Notes vary from run to run, so `--repeat 3` runs each session three times and reports the median. Every sentence the verifier did not pass goes to `<label>-review.csv` with the transcript lines it cited; a clinician marks each one `real_error` (the note was wrong and was caught) or `wrongly_blocked` (the sentence was fine). `review_summary.py` turns the marked sheet into three numbers per session: passed, real errors caught, wrongly blocked, plus flagged sentences per note (the therapist's extra clicks).

### Measuring the verifier

```bash
python3 scripts/verifier_eval.py
```

Runs the verifier on 48 note sentences about the simulated sessions: 18 correct ones and 30 with a known error (wrong number, time word, pronoun or speaker, reversed risk statement, invented content, overstated frequency, unmade diagnosis, wrong citation). Reports how many wrong sentences block signing and how many correct ones are flagged by mistake, per error type, in [docs/verifier-eval](docs/verifier-eval).

"Blocked" has one meaning here and in every current file: the sentence stops signing until the therapist acts, that is, it is marked unsupported, or it is weak and held (about risk, rejected by the model, or citing an instruction-like line). The B70 files from 2026-11-07 used an older meaning (unsupported only) and older rules; they are labelled "before the fixes" below and are not comparable with the current figure.

| Run | Date | Wrong sentences blocked | Correct sentences blocked | Definition and rules |
| --- | --- | --- | --- | --- |
| Rule layers only, no model | 2026-11-12 | 28/30 | 2/18 | current |
| qwen2.5:7b, laptop | 2026-11-08 | 27/30 | 1/18 | current definition, rules before the 2026-11-12 fixes |
| Qwen3-14B, B70 | 2026-11-07 | 26/30 | 0/18 | before the fixes: old definition, old rules |
| Qwen3-32B, B70 | 2026-11-07 | 26/30 | 0/18 | before the fixes: old definition, old rules |

The runs with a model have not been repeated since the fixes; re-running them on the B70 is pending. The cases were written by the team, so treat these numbers as a regression check, not an independent accuracy figure.

### Transcribing real audio

```bash
pip install -r requirements-asr.txt
HAVEN_ASR_MODEL=small python3 -m haven
```

Use "上傳會談錄音" in the client page. The first run downloads the Whisper model.

**On the B70**, Whisper runs as a second vLLM server on the same card, next to the note model. The weights (about 18 GB for the 32B model, 1.6 GB for Whisper) and the XPU Docker image are downloaded on the first start, which takes longer than the rest of the setup:

```bash
PORT=8001 UTIL=0.12 CONTAINER=vllm-asr bash scripts/b70-vllm.sh openai/whisper-large-v3-turbo whisper --max-model-len 448
until curl -s 127.0.0.1:8001/v1/models | grep -q whisper; do sleep 3; done   # start one server at a time
UTIL=0.8 bash scripts/b70-vllm.sh Qwen/Qwen3-32B-AWQ qwen3-32b-awq
until curl -s 127.0.0.1:8000/v1/models | grep -q qwen3; do sleep 3; done
HAVEN_LLM=openai HAVEN_MODEL=qwen3-32b-awq HAVEN_ASR=openai python3 -m haven
```

Start Whisper first and wait for it: two servers loading at once fail each other's memory check. With Whisper loaded, 24.5 of the card's 30.3 GiB stay free, which is why the note model runs at `UTIL=0.8`.

**Measured once on the B70** (week of 2026-11-10, whisper-large-v3-turbo through vLLM, no prompt): C001-S04 lines #10–#12 read aloud by two people, 23.0 s of audio, transcribed in 0.5 s with a character error rate of 14.1%; Qwen3-32B-AWQ then guessed the speaker of all three segments correctly in 2.3 s. Three segments from one clip is a smoke test, not an accuracy figure, and 14.1% is above the 10% target. Result files: [docs/asr-eval/b70-whisper-turbo-real-voices.md](docs/asr-eval/b70-whisper-turbo-real-voices.md). One simulated 36-minute session (C002-L50) was drafted and verified in 63.9 s by Qwen3-32B on the same card, before the 2026-11-12 fixes and in one run: see [docs/RESULTS.md](docs/RESULTS.md).

Recordings are streamed to a temp file, sent to the local server, and deleted after transcription. Then the local LLM guesses from the words who is speaking (one therapist, one client). There is no acoustic diarization yet, so the guesses are shown as 「（推測）」 and treated with care:

- The risk agent scans every line whose speaker is guessed or unknown, and a cue keeps its level whoever the model guessed said it (「我想燒炭」 stays at the top level). Only a question addressed to 「你」 is lowered to "review" and marked as possibly the therapist asking.
- Screening questions, safety steps and checklist items count only on lines known to be the therapist's (prepared transcripts). For an upload the panel says it cannot tell whether suicide was asked about, instead of saying it was not.
- A note sentence about what the client said, or about risk, that cites a guessed line is marked "支持不足" with the reason, and a weak risk sentence blocks signing until the therapist confirms it.

### Tests

```bash
python3 -m unittest discover -s tests -v
```

## Demo walkthrough

Before presenting, put the demo in a clean state. A note signed in an earlier run stays signed (that is the point of signing), so the signing step cannot be shown twice without this:

```bash
python3 scripts/reset_demo.py
python3 -m haven
```

`reset_demo.py` moves the current database aside as `data/haven.db-backup-<time>` (nothing is deleted), starts an empty one and drafts the three demo sessions with the current engine. It refuses to run if the data directory holds a session not marked simulated.

- **Without a model**, the rule engine only quotes the transcript, so every sentence passes and there is nothing red to show. The script therefore adds one wrong sentence to C001-S04's plan, 「安排下週五提前會談。」 citing line #19, where the therapist says 這週五. The session page says in a banner that the sentence was planted for the demonstration, and the audit log records it. It is the error qwen2.5:7b made in the first recorded demo. `--no-example` leaves it out.
- **With a model**, nothing is planted: the model's own flagged sentences are the demonstration, and they differ from run to run.
- `--from <file>` starts from a database prepared earlier instead of an empty one, with its signatures removed, for example a local `data/haven.demo.db` made with `scripts/prepare_demo.py` while a model was running. That file is not in the repository (databases are ignored by git). Its drafts are re-checked under the current rules, and paraphrased sentences pass only if the same model is running to check them.

Then:

1. **小安** shows five outcome reminders: PHQ-9, GAD-7 and BSRS-5 have not improved reliably after 4 sessions, PHQ-9 item 9 scored 1, and the BSRS-5 suicide item scored 2.
2. Open **第 4 次** (C001-S04). The risk panel groups cues by category: 「活著好累…消失算了」 (#10) under suicidal ideation, and 「沒有真的想要怎麼做」 (#12) kept for review because it is negated. Its checklist shows the therapist asked about suicide (#11), frequency (#13), protective factors (#15) and proposed a safety plan (#17, #19, #20), and that access to means and past attempts were not discussed.
3. Click the segment number beside any note sentence to mark the transcript lines behind it. Only the transcript column scrolls.
4. The counter above the note reads 「AI 草稿 14 句｜✓ 13 句有逐字稿支持｜✗ 1 句未能證實｜1 句被攔下，擋住簽核」, and the red sentence shows why: 時間詞「下週」不在引用的逐字稿中. Rewrite it as 「下次會談提前到這週五。」. An edited sentence is marked 「已修改，尚未驗證」 and signing is disabled until it has been verified again, which happens when you leave the box or press 重新驗證. **示範：插入捏造句** adds a sentence that is not in the transcript to show it being caught; remove it with **刪除**, or keep a flagged sentence with **保留此句（我已核對）**. **＋ 新增句子** adds a sentence of your own. A sentence that cites no transcript line (yours, or the planted one) is kept with **保留此句（寫下依據）**: you write what it is based on, and that basis is stored in the signed note and the audit log. The server refuses to sign an uncited sentence without one. The yellow demo notice goes away once the planted sentence is fixed or deleted.
5. **核對完成，簽核** opens a dialog that lists the flagged sentences you kept and the risk cues you left out, and asks for your name and a tick on 「我已逐句核對」. The server checks the whole note again. After signing, the page shows the signed note read-only with its hashes and an addendum box.
6. Back on the client page, ask **「哪幾次提到父親？」** to search across sessions.

Leaving a session with unsigned edits asks first: a draft's edits live in the page until it is signed (there is no saved draft yet).

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `HAVEN_LLM` | `auto` | `auto` uses Ollama if the model is available, `demo` forces the rule-based engine, `ollama` requires the model, `openai` uses a local OpenAI-compatible server (vLLM, llama.cpp `llama-server`, OpenVINO Model Server) |
| `HAVEN_LLM_URL` | `http://127.0.0.1:11434` (`:8000` for `openai`) | Local model server; non-local addresses are refused |
| `HAVEN_MODEL` | `qwen2.5:7b` | Model name on the server |
| `HAVEN_ASR` | `faster-whisper` | `faster-whisper` transcribes in-process; `openai` sends audio to a local server with the OpenAI transcription API (vLLM serving Whisper) |
| `HAVEN_ASR_URL` | `http://127.0.0.1:8001` | Local transcription server for `openai`; non-local addresses are refused |
| `HAVEN_ASR_MODEL` | `small` (`whisper` for `openai`) | faster-whisper model size, or the served model name |
| `HAVEN_ASR_TIMEOUT` | `900` | Seconds to wait for a transcription |
| `HAVEN_ASR_PROMPT` | a short Traditional Chinese line for `faster-whisper`, none for `openai` | Text given to Whisper before the audio. On the B70 a prompt made whisper-large-v3-turbo drop or repeat the last utterance of a clip, so the server gets none |
| `HAVEN_HOST` / `HAVEN_PORT` | `127.0.0.1` / `8765` | Where the UI is served. **Leave the host at `127.0.0.1`.** Haven has no login: on any other address everyone who can reach the port can read every transcript and sign notes. LAN use is not supported yet; besides, requests whose `Host` header is not `HAVEN_HOST`, `localhost` or `127.0.0.1` are refused, so `0.0.0.0` does not make the UI reachable by the machine's LAN address. Haven prints a warning at start when the host is not loopback |
| `HAVEN_DATA_DIR` | `data/` in the repository | Where transcripts, the client file and the database are kept. For real use, point it outside the repository |
| `HAVEN_LLM_TIMEOUT` | `180` | Seconds to wait for the note model |

## Stage II plan (Arc Pro B70)

| Item | Status |
| --- | --- |
| LLM | Running: Qwen3-32B at 4-bit on one card with vLLM. Not done: a comparison of note quality between models by a psychologist (the pass counts above do not measure it) |
| ASR | Built: Whisper on the GPU through vLLM, speakers guessed by the local LLM; measured once on a 23-second clip. Not done: a recording of 10 minutes or more, acoustic diarization, a speaker-correction step in the UI |
| Storage | Files are private to the account (0600/0700). Not done: SQLCipher encryption at rest; use full-disk encryption meanwhile |
| Validation | Not done: 10–20 simulated sessions labelled by a licensed psychologist |

Targets, with what has been measured so far. A target without a measurement is a goal, not a result:

| Metric | Target | Measured |
| --- | --- | --- |
| 50-minute session to draft note, including speech-to-text | ≤ 5 minutes | pending (only 2–4 minute sessions, without speech-to-text: 12–29 s) |
| Concurrent rooms, 50-minute sessions, Whisper on the same card | ≥ 4 | pending |
| Peak memory and power draw under that load | – | pending |
| Character error rate | ≤ 10% | 14.1% on one 23-second clip; a longer recording is pending |
| Note sentences backed by the transcript, as judged by a clinician | ≥ 95% | pending (needs the clinician's reading of flagged sentences) |
| Risk-cue recall vs. psychologist labels | ≥ 90% | pending (no psychologist-labelled set yet; see Limitations) |
| Outbound network connections during a session | 0 (packet capture) | pending |

## Limitations

- **Risk detection is word matching and its lists are 待心理師確認.** `tests/test_risk_recall.py` reports recall per category on the 64 sentences from the 2026-11-12 clinical review (before: about 22% on the suicide sentences; now 64/64). The lists were written with those sentences in view, so that figure is a regression check, not accuracy. On 16 risk sentences written afterwards and not used to build the lists, 3 were flagged (19%); six everyday sentences such as 「想到期末考就想死」 still raise a high-level flag. "No cue found" never means "no risk". A local-LLM pass that can only add flags, and a psychologist-labelled test set, are still to do.
- The reporting cues quote article numbers as given in the review; check them against 全國法規資料庫 before relying on them. Haven has no reporting workflow yet: it shows the prompt and, at signing, requires the cue to be in the note or left out with a reason.
- **No encryption at rest and no accounts.** Anyone with this user account or the disk can read everything; the audit log does not say who acted; `signed_by` is a name typed into a dialog. Haven is not presented as compliant with the Personal Data Protection Act: consent versions and withdrawal, retention and deletion after 10 years, data-subject requests and handling of minors are not built.
- **Loopback is not a security boundary.** Any program on the machine can call the API with the `X-Haven` header, including a model container started with `--net=host` (as `scripts/b70-vllm.sh` does). The launcher is a demonstration script: its hardening options are untested on the B70.
- **Draft edits are saved when they are verified**, which happens a moment after each change (with the confirmations, written bases and risk-cue reasons). A sentence still being typed is not saved yet; the page asks before leaving. 「還原成 AI 原稿」 discards the working draft. The saved draft sits in `data/haven.db` unencrypted, like everything else there.
- The rule-based engine is for the prototype.
- The verifier's bigram overlap is a first filter. Paraphrased sentences are sent to the local LLM for a second check when one is running. Without a model, a sentence with an unmatched clause is marked weak but does not block signing unless it is about risk.
- Writing long sessions in parts of 60 segments has been tested with a stand-in model only, not yet on the B70; each part is written without seeing the others.
- The not-on-track rule (not reliably improved by the third score, still in the clinical range) is a heuristic, not a validated expected-recovery curve; it and the BSRS-5 stand-in threshold are 待心理師確認. "Clinically significant change" is judged per questionnaire, not on PHQ-9 and GAD-7 together as IAPT does.
- Case memory is keyword matching with hand-written word families; a topic described in other words is missed.
- Uploaded audio has no acoustic speaker diarization yet. Speakers are guessed by the LLM from the words; the therapist cannot yet correct a label in the UI, so lines from guessed speakers are flagged more and counted less (see "Transcribing real audio").
- A LAN deployment needs therapist accounts, per-therapist access to clients and TLS; none exists, so Haven is single-machine only (see `HAVEN_HOST`).
- The negation rule compares the same word in the sentence and in the cited lines, clause by clause. It does not read a denial placed after the word (「自殺意念：無」), and for a risk sentence in other words than the source's it falls back to a coarse check that flags some correct sentences; the therapist confirms them.
- The checklist detects whether a topic came up by keywords near suicide talk. It cannot judge the quality of the inquiry, and 「安全計畫」 is ticked when one is mentioned or proposed, not when its content is complete.

## Team

Team **NTU心港**, two members, for the ASUS UGen AI League 2026:

- Product and clinical concept
- Software and hardware

## References

- Psychologists Act (心理師法), Art. 25.
- Lambert, M. J., Whipple, J. L., & Kleinstäuber, M. (2018). Collecting and delivering progress feedback: A meta-analysis of routine outcome monitoring. *Psychotherapy, 55*(4).
- Olson, K. D., Meeker, D., Troup, M., Barker, T. D., Nguyen, V. H., Manders, J. B., Stults, C. D., Jones, V. G., Shah, S. D., Shah, T., & Schwamm, L. H. (2025). Use of ambient AI scribes to reduce administrative burden and professional burnout. *JAMA Network Open, 8*(10), e2534976. https://doi.org/10.1001/jamanetworkopen.2025.34976

## License

To be decided before public release.
