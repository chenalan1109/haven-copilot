# Haven 心港 — an on-premises AI copilot for psychotherapists

**ASUS UGen AI League Hackathon · Workplace AI · Battlefield Thunderstorm (ASUS UGen Intel Arc Pro B70 32GB)**

Haven turns a therapy session into a draft progress note, risk cues and outcome-tracking alerts. Everything runs on one machine inside the clinic. Session audio and transcripts never leave the room, so therapists get AI documentation help without sending their clients' most sensitive data to a cloud service.

> All data in this repository is from **simulated sessions** performed by actors from a script. It contains no real client information.

## Why on-device

- **Privacy is the product.** In Taiwan, health and medical data is a special category of personal data under the Personal Data Protection Act (Art. 6). Existing AI note tools for therapists (Upheal, Mentalyc, Eleos) are cloud services.
- **The record has to last.** The Psychologists Act (Art. 25) requires practice records to be kept for at least 10 years. Notes that are wrong or invented stay wrong for a decade, so every sentence must be traceable.
- **Local hardware is now big enough.** A 32GB card such as the Arc Pro B70 can hold a 27B–34B model at 4-bit, which is the size needed for usable Traditional Chinese clinical notes.

## How it works

```mermaid
flowchart LR
    A[Session audio<br/>with client consent] --> ASR[ASR agent<br/>Whisper, timestamps]
    Q[Waiting-room questionnaires<br/>BSRS-5, PHQ-9, GAD-7] --> MEM
    ASR --> ORCH[Orchestrator agent]
    ORCH --> W[Note-writer agent<br/>SOAP / DAP]
    W --> V[Verifier agent<br/>every sentence vs. transcript]
    ORCH --> R[Risk agent<br/>cues + exact quotes]
    ORCH --> O[Outcome agent<br/>reliable change, not-on-track]
    V --> MEM[(Case memory<br/>local SQLite)]
    O --> MEM
    ORCH <--> UI[Therapist UI<br/>review, edit, sign]
    X[Cloud] -. no connection .- ORCH
```

| Agent | What it does | Where |
| --- | --- | --- |
| ASR | Speech to timestamped segments (faster-whisper, int8) | `haven/transcript.py` |
| Note writer | Drafts SOAP or DAP notes; every sentence cites segment ids | `haven/agents/writer.py` |
| Verifier | Checks each sentence against the segments it cites, in three layers: hard rules (numbers, time words and gendered pronouns must appear in the cited lines; a risk sentence must keep the cited lines' negation), word overlap, then one batched local-LLM check for paraphrases. Unsupported sentences block signing until the therapist edits, deletes or confirms them | `haven/agents/verifier.py` |
| Risk | Flags suicide, self-harm, violence and functioning cues with the exact quote; keeps negated cues for review; when suicide cues appear, shows which parts of a risk inquiry the session covered (ideation, frequency, plan, intent, access to means, past attempts, protective factors, safety plan, crisis resources) and which to consider asking or documenting | `haven/agents/risk.py` |
| Outcome | Routine outcome monitoring: reliable change (PHQ-9: 6, GAD-7: 4), clinically significant change, not-on-track heuristic with a review prompt, PHQ-9 item 9 and BSRS-5 suicide-item alerts; writes the score lines into the note's objective section | `haven/agents/outcome.py` |
| Case memory | Answers "which sessions mentioned her father?" from that client's own sessions only | `haven/agents/memory.py` |
| Orchestrator | Runs the agents, times each one, stores the result and an audit log | `haven/orchestrator.py` |

**Human in the loop:** Haven only produces drafts and prompts. A note is filed only after the therapist reviews and signs it. Haven does not diagnose or give any output to the client, and it does not analyse facial expressions.

**Privacy and safety guards in the code** (tested in `tests/`):
- The LLM client refuses any endpoint that is not loopback or a private LAN address, and never goes through an HTTP or system proxy.
- The server binds to `127.0.0.1`, rejects requests whose `Host` header is not its own (DNS rebinding), and requires an `X-Haven` header on every POST, so another website open in the browser cannot sign or upload.
- The server, not only the UI, refuses to sign a note with an unchecked sentence or an unsupported one the therapist has not kept. A signed note is never overwritten. The audit log records how many flagged sentences the therapist kept.
- Uploads require the client's written consent to recording. The audio is written to a temporary file and deleted right after transcription.
- Questionnaire scores enter the note from the score data, not from the model, so a number in the objective section is never invented.
- Every processing, query and signing action is written to an audit log.

## Quick start (laptop, no GPU needed)

Requires Python 3.10+. The core has no third-party dependencies.

```bash
python3 -m haven
```

Open http://127.0.0.1:8765. Without a local model, Haven uses its **rule-based demo engine**, which selects and rewrites what was said. It cannot invent content, but the notes read like quotes.

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

**Measured on a MacBook Air M2 (8GB) with qwen2.5:7b** (simulated sessions of about 2–4 minutes of speech):

| Session | Total time | Sentences backed by the transcript |
| --- | --- | --- |
| C001-S03 | 63 s | 9 / 12 |
| C001-S04 | 44 s | 7 / 12 |
| C002-S05 | 37 s | 7 / 10 |

Score lines filled in from the questionnaires are not counted. What the verifier caught in these runs: "下週五" where the session said "這週五", "近兩週" attached to a statement that had no time frame, and feelings ("自責") the cited line did not contain. It also flags some correct paraphrases; the therapist clears those with "確認無誤". A 7B model on a laptop is the floor; Stage II moves to a larger model on the Arc Pro B70.

### Transcribing real audio

```bash
pip install -r requirements-asr.txt
HAVEN_ASR_MODEL=small python3 -m haven
```

Use "上傳會談錄音" in the client page. The first run downloads the Whisper model.

### Tests

```bash
python3 -m unittest discover -s tests -v
```

## Demo walkthrough

1. **小安** shows four outcome alerts: PHQ-9, GAD-7 and BSRS-5 are not improving after 4 sessions, and the BSRS-5 suicide item scored 2.
2. Open **C001-S04**. The risk panel flags 「活著好累…消失算了」 (#10) as suicidal ideation, and keeps 「沒有真的想要怎麼做」 (#12) for review because it is negated. Its checklist shows the therapist asked about suicide (#11), frequency (#13), protective factors (#15) and made a safety plan (#17, #19, #20), and that access to means and past attempts were not discussed.
3. Click any note sentence to jump to the transcript lines behind it.
4. Red sentences show why they were flagged. Rewrite "安排下週五提前會談" as "下次會談提前到這週五。" and the verifier clears it; click **確認無誤** on a correct paraphrase. **加入測試句** inserts a sentence that is not in the transcript to show it being caught. Signing stays blocked until every red sentence is fixed, removed or confirmed.
5. Ask **「哪幾次提到父親？」** to search across sessions.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `HAVEN_LLM` | `auto` | `auto` uses Ollama if the model is available, `demo` forces the rule-based engine, `ollama` requires the model |
| `HAVEN_LLM_URL` | `http://127.0.0.1:11434` | Local model server; non-local addresses are refused |
| `HAVEN_MODEL` | `qwen2.5:7b` | Model name on the server |
| `HAVEN_ASR_MODEL` | `small` | faster-whisper model size |
| `HAVEN_HOST` / `HAVEN_PORT` | `127.0.0.1` / `8765` | Where the UI is served |

## Stage II plan (Arc Pro B70)

| Item | Plan |
| --- | --- |
| LLM | 14B–32B model at 4-bit (Qwen3, Gemma 3 or MediaTek Breeze 2) served by OpenVINO GenAI or llama.cpp with the OpenVINO backend |
| ASR | Whisper large-v3 or Breeze-ASR on the GPU; pyannote speaker diarization |
| Storage | SQLCipher encryption at rest, full-disk encryption |
| Validation | 10–20 simulated sessions labelled by a licensed psychologist |

Targets to validate on the B70. These are goals, not measured results yet:

| Metric | Target |
| --- | --- |
| 50-minute session to draft note | ≤ 5 minutes |
| Concurrent rooms | ≥ 4 |
| Character error rate | ≤ 10% |
| Note sentences backed by the transcript | ≥ 95% |
| Risk-cue recall vs. psychologist labels | ≥ 90% |
| Outbound network connections during a session | 0 (packet capture) |

## Limitations

- The rule-based engine and the risk lexicon are for the prototype. Lexicon matching misses indirect expressions; the Stage II LLM pass and psychologist-labelled test data address this.
- The verifier's bigram overlap is a first filter. Paraphrased sentences are sent to the local LLM for a second check when one is running.
- The not-on-track rule is a simple heuristic, not a validated expected-recovery curve.
- Uploaded audio is not yet split by speaker. Until Stage II diarization, questions are treated as the therapist's and are not flagged as disclosures.
- There is no login yet: the server only listens on the machine itself. A LAN deployment in Stage II needs therapist accounts, per-therapist access to clients and TLS.
- The negation rule for risk sentences is deliberately strict and flags some correct sentences; the therapist confirms them.
- The checklist detects whether a topic came up by keywords. It cannot judge the quality of the inquiry.

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
