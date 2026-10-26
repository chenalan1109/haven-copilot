# Haven — Stage I video script (≤ 3:00)

English voice-over over the deck and a screen recording. The demo includes a short clip of the simulated session in Chinese with English subtitles. About 390 words of narration at ~140 words per minute, plus a 25-second clip, gives about 2:55.

**Before recording**
- **Don't** re-run `scripts/prepare_demo.py`. The stored C001-S04 note already contains the 「安排下週五提前會談」 error the demo needs, and a fresh run may not reproduce it.
- Back up the database first: `cp data/haven.db data/haven.demo.db`. After a practice run, restore it with `cp data/haven.demo.db data/haven.db`. This also clears practice signatures.
- Keep Ollama running: 重新驗證 calls the local model.
- Browser at about 1400 px wide, zoom 110–125%, so the Chinese text is readable in a 1080p video.
- Deck in Present mode. Screen recording in a second window.

---

## 0:00–0:12 · Hook — slide 1 (cover)

**VO:**
Every week, therapists write notes about the most private conversations people ever have. Most AI tools that help them send those conversations to the cloud. Haven doesn't.

## 0:12–0:40 · Problem — slides 2 and 3

**VO:**
Therapists face three problems at once. In Taiwan, records must be kept for ten years, and the writing never stops. Health data is a special category under Taiwan's data protection law, yet the leading AI note tools are cloud services. And five to ten percent of clients get worse in therapy, often without anyone noticing in time. Existing tools solve the paperwork, but not the privacy or the follow-up.

## 0:40–0:58 · Solution — slide 4

**VO:**
Haven is an AI copilot that runs on one machine inside the clinic. It records with consent, transcribes, drafts the note, checks every sentence against the transcript, raises risk and outcome alerts — and then the therapist decides. Haven never diagnoses, and nothing is filed without the therapist's signature.

## 0:58–1:10 · Demo: pre-session brief — screen recording, `?client=C001`

**ON SCREEN:** Client 小安. The four alerts, then the trend charts.
**Caption (top):** Simulated client · actors · no real data

**VO:**
Here's the prototype. Before her fourth session, Haven warns that 小安's depression and distress scores aren't improving, and that she scored on the suicide item.

## 1:10–1:35 · Demo: the session — clip of actors, Chinese audio

**ON SCREEN:** The actors (or the transcript scrolling) with English subtitles. No voice-over.

| # | Speaker | Chinese (audio) | English subtitle |
|---|---|---|---|
| 10 | Client | 有時候會覺得活著好累，會想說如果消失算了，大家可能也不會怎麼樣。 | Sometimes I'm so tired of living. Maybe I should just disappear. No one would really care. |
| 11 | Therapist | 謝謝你願意告訴我。……你有想過要結束自己的生命嗎？ | Thank you for telling me. Have you thought about ending your life? |
| 12 | Client | 有想過，但是沒有真的想要怎麼做，就是晚上一個人的時候會冒出來。 | I have, but I don't really want to do anything. It comes up at night when I'm alone. |

## 1:35–1:55 · Demo: risk panel — screen recording, `?session=C001-S04`

**ON SCREEN:** Risk panel. Click the flag for #10 so the transcript line highlights. Hover over #12.

**VO:**
After the session, the risk agent flags that line with the exact quote. When she says she has no plan, Haven doesn't treat that as all-clear — it keeps it for review. It also checks that the therapist asked directly, made a safety plan, and gave the 1925 hotline.

## 1:55–2:20 · Demo: verifier — same screen, note panel

**ON SCREEN:**
1. Scroll to the red sentence 「安排下週五提前會談」 and its reason, 時間詞「下週」不在引用的逐字稿中.
2. Click it to show transcript line #19: 「我們下次提前到這週五再見一次」.
3. Change 下週五 to 這週五, then click 重新驗證. The sentence turns green.
4. Confirm the remaining red sentences, then click 確認並簽核.

**Subtitle for the #19 line:** "Let's move our next session up to this Friday."

**VO:**
Every sentence in the note cites the lines behind it. Here the model wrote *next* Friday, but the therapist said *this* Friday. The verifier caught it. I fix the date, it re-checks, and only when every red sentence is fixed or confirmed can I sign.

## 2:20–2:40 · Architecture and hardware — slides 8 and 9

**VO:**
Six agents run on one server in the clinic, and the code refuses to talk to anything outside the local network. Today it runs on an 8 GB laptop with a 7-billion-parameter model. On the ASUS UGen Arc Pro B70, 32 gigabytes holds a model four times larger, plus speech recognition, on one card.

## 2:40–2:52 · Results and business — slides 11 and 12

**VO:**
On the laptop, Haven processes a session in about a minute, and flags what it can't back. It's sold as one machine per clinic plus a subscription — so every clinic that adopts Haven runs on ASUS hardware.

## 2:52–3:00 · Close — slide 14

**ON SCREEN:** GitHub link. End card: *Haven 心港 · [Team name]*. Small line underneath: *In Taiwan, the 1925 安心專線 is available 24 hours a day.*

**VO:**
Haven: AI help for therapists, without the data ever leaving the room. Thank you.

---

## Notes

- **Timing.** If you run long, cut the GAD-7 mention and shorten the risk paragraph first. Never cut the verifier demo: it is the strongest proof of innovation.
- **Actors.** Two people read #10–#12 from `python3 scripts/print_script.py C001-S04`. Record them as audio over the scrolling transcript if you'd rather not show faces.
- **Pronunciation.** Say 小安 as "Xiǎo Ān". Say "B-seventy".
- **Upload.** Upload to YouTube as **Unlisted**. Burn the subtitles in (CapCut works) or upload an .srt. Put the YouTube and GitHub links in the submission form.
