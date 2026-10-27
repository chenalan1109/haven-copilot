# Haven — Stage I video script (≤ 3:00), v2

English voice-over over the deck and a screen recording. The demo includes a short clip of the simulated session in Chinese with English subtitles. About 400 words of narration at ~140 words per minute, plus a 25-second clip, comes to about 2:55.

**Before recording**
- Restore the demo data: `cp data/haven.demo.db data/haven.db`. This also clears practice signatures. Do it again after every practice run.
- **Don't** re-run `scripts/prepare_demo.py`. The stored C001-S04 note contains the 「安排下週五提前會談」 error the demo needs, and a fresh run may not reproduce it.
- Keep Ollama running (`OLLAMA_HOST=127.0.0.1:11434 ollama serve`). 重新驗證 may call the local model.
- Set the browser to about 1400 px wide and 110–125% zoom so the Chinese text is readable in a 1080p video. Run the deck in Present mode and the screen recording in a second window.

---

## 0:00–0:12 · Hook — slide 1 (cover)

**ON SCREEN (first 3 s, small caption):** *Content note: includes a simulated conversation about suicidal thoughts.*

**VO:**
Every week, therapists write notes about the most private conversations people ever have. Most AI tools that help them send those conversations to the cloud. Haven doesn't.

## 0:12–0:38 · Problem — slides 2 and 3

**VO:**
Therapists face three problems at once. In Taiwan, records must be kept for ten years, and the writing never stops. Health data is a special category under Taiwan's data protection law, yet the leading AI note tools are cloud services. And five to ten percent of clients get worse in therapy, often without anyone noticing in time.

## 0:38–0:55 · Solution — slide 4

**VO:**
Haven is an AI copilot that runs on one machine inside the clinic. It transcribes the session, drafts the note, checks every sentence against the transcript and raises alerts. Then the therapist decides. Haven never diagnoses, and nothing is filed without the therapist's signature.

## 0:55–1:08 · Demo: pre-session brief — screen recording, `?client=C001`

**ON SCREEN:** Client 小安. The five alerts, the single 建議 line, then the trend charts.
**Caption (top):** Simulated client · actors · no real data

**VO:**
Here's the prototype. Before her fourth session, Haven shows that 小安 isn't improving and that both suicide items on her questionnaires are positive. It also suggests a next step, not just a red flag.

## 1:08–1:33 · Demo: the session — clip of actors, Chinese audio

**ON SCREEN:** The actors (or the transcript scrolling) with English subtitles. No voice-over.

| # | Speaker | Chinese (audio) | English subtitle |
|---|---|---|---|
| 10 | Client | 有時候會覺得活著好累，會想說如果消失算了，大家可能也不會怎麼樣。 | Sometimes I'm so tired of living. Maybe I should just disappear. No one would really care. |
| 11 | Therapist | 謝謝你願意告訴我。……你有想過要結束自己的生命嗎？ | Thank you for telling me. Have you thought about ending your life? |
| 12 | Client | 有想過，但是沒有真的想要怎麼做，就是晚上一個人的時候會冒出來。 | I have, but I don't really want to do anything. It comes up at night when I'm alone. |

## 1:33–1:58 · Demo: risk panel — screen recording, `?session=C001-S04`

**ON SCREEN:**
1. Click the flag for #10 so the transcript line highlights.
2. Point at #12 and its 「含否定語，請確認」.
3. Slowly move down the checklist. Stop on the two orange items: 工具或手段可及性 and 過去自殺或自傷史.

**VO:**
After the session, the risk agent flags that line with the exact quote. "No plan" is kept for review, not treated as all-clear. Then it checks the inquiry itself. Ideation, frequency, a safety plan and the 1925 hotline were covered. Access to means and past attempts were not, so Haven suggests asking.

## 1:58–2:22 · Demo: verifier — same screen, note panel

**ON SCREEN:**
1. Show section O. The three score lines are tagged 量表.
2. Scroll to the red sentence 「安排下週五提前會談。」 with the reason 時間詞「下週」不在引用的逐字稿中.
3. Click it so transcript line #19 shows: 「我們下次提前到這週五再見一次」.
4. Replace the whole sentence with **「下次會談提前到這週五。」**, then click 重新驗證. It turns green. It passes on word overlap alone, so the result doesn't depend on the model.
5. Click 確認無誤 on the remaining red sentences, then click 確認並簽核.

**Subtitle for the #19 line:** "Let's move our next session up to this Friday."

**VO:**
Scores come straight from the questionnaires, so the model never writes a number. Here the model wrote *next* Friday, but the therapist said *this* Friday. The verifier caught it. The therapist fixes it, it re-checks, and the server won't sign until every red sentence is fixed or kept.

## 2:22–2:40 · Architecture and hardware — slides 8 and 9

**VO:**
Six agents run on one server in the clinic, and the code refuses anything outside the local network. On the ASUS UGen Arc Pro B70, 32 gigabytes holds a 27-billion-parameter model and speech recognition together, enough for four therapy rooms at once.

## 2:40–2:52 · Results and business — slides 11 and 12

**VO:**
On a laptop, Haven already processes a short session in about a minute, and flags what it can't back. It's sold as one machine per clinic plus a subscription.

## 2:52–3:00 · Close — slide 14

**ON SCREEN:** GitHub link. End card: *Haven 心港 · Team NTU心港*. Small line underneath: *In Taiwan, the 1925 安心專線 is available 24 hours a day.*

**VO:**
Haven: AI help for therapists, without the data ever leaving the room. Thank you.

---

## Notes

- **Timing.** If you run long, cut the sentence about scores in the verifier part first. Never cut the checklist or the 下週五 fix: they carry the clinical and technical innovation.
- **Actors.** Two people read #10–#12 from `python3 scripts/print_script.py C001-S04`. The clip is audio only, over the scrolling transcript.
- **Pronunciation.** Say 小安 as "Xiǎo Ān". Say "B-seventy".
- **Upload.** Upload to YouTube as **Unlisted**. Burn the subtitles in (CapCut works) or upload an .srt. Put the YouTube and GitHub links in the submission form.

---

## Audio to record (everything else is built from the deck and the app)

The video is assembled from deck slides, screen captures of the prototype, captions and these audio files. Nobody appears on camera. Record in a quiet room with a phone held about 20 cm away, as WAV or M4A. Leave 1 second of silence before and after each take. One file per row, named as shown.

| File | Who | Content | Length |
|---|---|---|---|
| `vo-01-hook.m4a` | Narrator | 0:00–0:12 VO | ~10 s |
| `vo-02-problem.m4a` | Narrator | 0:12–0:38 VO | ~24 s |
| `vo-03-solution.m4a` | Narrator | 0:38–0:55 VO | ~16 s |
| `vo-04-brief.m4a` | Narrator | 0:55–1:08 VO | ~12 s |
| `clip-10-client.m4a` | Client voice | Line #10 in Chinese | ~6 s |
| `clip-11-therapist.m4a` | Therapist voice | Line #11 in Chinese | ~5 s |
| `clip-12-client.m4a` | Client voice | Line #12 in Chinese | ~6 s |
| `vo-05-risk.m4a` | Narrator | 1:33–1:58 VO | ~23 s |
| `vo-06-verifier.m4a` | Narrator | 1:58–2:22 VO | ~22 s |
| `vo-07-hardware.m4a` | Narrator | 2:22–2:40 VO | ~16 s |
| `vo-08-results.m4a` | Narrator | 2:40–2:52 VO | ~11 s |
| `vo-09-close.m4a` | Narrator | 2:52–3:00 VO | ~6 s |

- The narrator and the client voice can be the same person, but the therapist voice should be the other team member, so the clip sounds like two people.
- Read the client lines slowly and quietly. Don't act distress; the words carry it.
- If a VO file runs longer than its length, that's fine: the visuals are timed to the audio afterwards, and the "Timing" note says what to cut.
