"use strict";

// Haven therapist UI. Talks only to the local Haven server (same origin).

const SECTION_NAMES = {
  S: "S 主觀資料", O: "O 客觀資料", A: "A 評估", P: "P 計畫", D: "D 資料", R: "R 風險與安全",
};
// Shown under a section title: what the draft cannot contain and the therapist adds.
const SECTION_HINTS = {
  O: "量表分數由系統填入。精神狀態觀察（外觀、情感、思考、定向、風險行為）逐字稿看不出來，請心理師自行補寫。",
  R: "逐字稿中的風險線索、保護因子與安全措施；不受句數限制。提議而未完成的安全計畫會寫成「心理師提議」。",
};
// Describes the cues found in the transcript, not the client's risk level.
const RISK_NAMES = { none: "未偵測到風險線索", review: "有需留意的線索", high: "有自殺或自傷等高關注線索", critical: "提及計畫或工具" };
const STATUS_NAMES = { supported: "用字與引用段落相符", weak: "支持不足", unsupported: "無支持證據" };
const AGENT_NAMES = { asr: "轉寫", writer: "紀錄", verifier: "驗證", risk: "風險", outcome: "成效" };

let currentClient = null;
let currentSession = null;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

async function api(path, opts = {}) {
  // The server refuses POSTs without this header (cross-site request protection).
  if (opts.method === "POST") opts.headers = { ...(opts.headers || {}), "X-Haven": "1" };
  let res, data = {};
  try {
    res = await fetch(path, opts);
  } catch (err) {
    throw new Error("連不上本機的 Haven 伺服器，請確認程式還在執行。");
  }
  try { data = await res.json(); } catch (err) { /* not JSON */ }
  if (!res.ok) {
    // The server sends a Chinese message for the therapist; fall back to a plain one.
    const e = new Error(data.message_zh || HTTP_MESSAGES[res.status] || `操作沒有完成（代碼 ${res.status}）。`);
    e.status = res.status;
    e.data = data;
    throw e;
  }
  return data;
}

const HTTP_MESSAGES = {
  400: "送出的資料格式不正確。",
  403: "伺服器拒絕了這個請求。",
  404: "找不到這筆資料。",
  409: "目前的狀態不允許這個操作。",
  500: "伺服器發生錯誤，請看終端機的訊息。",
};

function fmtDateTime(iso) {
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString("zh-TW", { hour12: false });
}

function fmtTime(sec) {
  const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

// ---------- status & client list ----------

async function loadStatus() {
  const s = await api("/api/status");
  const box = document.getElementById("status");
  box.replaceChildren(
    el("span", { class: "pill good" }, "本機運算 On-device"),
    el("span", { class: "pill" }, `雲端連線 ${s.cloud_calls}`),
    el("span", { class: "pill" }, `模型：${s.engine}`),
  );
}

async function loadClients() {
  const clients = await api("/api/clients");
  const list = document.getElementById("client-list");
  list.replaceChildren(...clients.map((c) => el("li", {
    "data-id": c.id,
    onclick: () => openClient(c.id),
  },
    el("span", {}, c.alias, el("span", { class: "sub" }, c.presenting_concern)),
    c.alert_count ? el("span", { class: "badge" }, `${c.alert_count} 警示`) : null,
  )));
}

function markActive(id) {
  document.querySelectorAll("#client-list li").forEach((li) => li.classList.toggle("active", li.dataset.id === id));
}

// ---------- client view ----------

function chart(m) {
  const w = 220, h = 90, pad = 14;
  const pts = m.history;
  const xs = (i) => pad + (pts.length === 1 ? 0 : (i * (w - 2 * pad)) / (pts.length - 1));
  const ys = (v) => h - pad - (v / m.max) * (h - 2 * pad);
  const color = m.status === "deteriorated" ? "var(--bad)" : m.status === "not_on_track" ? "var(--warn)" : ["improved", "recovered"].includes(m.status) ? "var(--good)" : "var(--accent)";
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${m.name} 從 ${m.baseline} 到 ${m.latest}`);
  const line = document.createElementNS(ns, "polyline");
  line.setAttribute("points", pts.map((p, i) => `${xs(i)},${ys(p.score)}`).join(" "));
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", color);
  line.setAttribute("stroke-width", "2");
  svg.append(line);
  pts.forEach((p, i) => {
    const c = document.createElementNS(ns, "circle");
    c.setAttribute("cx", xs(i)); c.setAttribute("cy", ys(p.score)); c.setAttribute("r", "3.5"); c.setAttribute("fill", color);
    const t = document.createElementNS(ns, "text");
    t.setAttribute("x", xs(i)); t.setAttribute("y", ys(p.score) - 7); t.setAttribute("text-anchor", "middle");
    t.setAttribute("font-size", "10"); t.setAttribute("fill", "var(--muted)");
    t.textContent = p.score;
    svg.append(c, t);
  });
  return el("div", { class: "chart" },
    el("div", { class: "title" }, el("span", {}, m.name), el("span", {}, `${m.latest}／${m.max}（${m.band}）`)),
    svg,
  );
}

async function openClient(id) {
  currentClient = id;
  markActive(id);
  const main = document.getElementById("main");
  main.replaceChildren(el("div", { class: "empty" }, "載入中…"));
  const brief = await api(`/api/clients/${id}/brief`);
  const frag = document.getElementById("tpl-client").content.cloneNode(true);
  const c = brief.client;
  frag.querySelector(".client-name").textContent = `${c.alias}・${c.age} 歲`;
  frag.querySelector(".concern").textContent = `主訴：${c.presenting_concern}`;

  const alerts = brief.outcome.alerts;
  frag.querySelector(".alerts").append(...(alerts.length
    ? alerts.map((a) => el("div", { class: `alert ${a.status}` }, `${a.name}：${a.message}`))
    : [el("div", { class: "alert ok" }, "量表追蹤：目前無警示")]));
  // One prompt for all not-improving measures, so it is read rather than skimmed.
  const review = alerts.find((a) => a.review);
  if (review) frag.querySelector(".alerts").append(el("div", { class: "review" }, `建議：${review.review}`));
  frag.querySelector(".charts").append(...brief.outcome.measures.map(chart));

  if (brief.last_session) {
    const ls = brief.last_session;
    frag.querySelector(".last-plan").append(
      el("div", {}, `上次會談：第 ${ls.session_no} 次（${ls.date}），風險線索：${RISK_NAMES[ls.risk_level]}`),
      brief.plan.length ? el("ul", {}, brief.plan.map((p) => el("li", {}, p))) : null,
    );
  }

  frag.querySelector(".session-buttons").append(...c.sessions.map((sid) =>
    el("button", { onclick: () => openSession(sid) }, `${sid} 檢視紀錄`)));

  const upForm = frag.querySelector(".upload-form");
  const upMsg = frag.querySelector(".upload-msg");
  upForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = upForm.audio.files[0];
    upMsg.textContent = "本機轉寫中，請稍候…";
    try {
      const q = new URLSearchParams({ client: id, session_id: upForm.session_id.value, consent: upForm.consent.checked ? "1" : "0", simulated: upForm.simulated.checked ? "1" : "0" });
      const r = await api(`/api/upload?${q}`, {
        method: "POST", headers: { "X-Filename": file.name }, body: file,
      });
      upMsg.textContent = "完成，錄音已刪除。";
      await loadClients();
      renderSession(r);
    } catch (err) {
      upMsg.textContent = `失敗：${err.message}`;
    }
  });

  const askForm = frag.querySelector(".ask-form");
  const askOut = frag.querySelector(".ask-result");
  askForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const r = await api(`/api/clients/${id}/ask?q=${encodeURIComponent(askForm.q.value)}`);
    askOut.replaceChildren(
      r.answer ? el("p", {}, r.answer) : null,
      r.hits.length ? null : el("p", {}, "沒有找到相關片段。"),
      ...r.hits.map((h) => el("div", { class: "hit" },
        el("div", { class: "meta" }, `第 ${h.session_no} 次會談・${fmtTime(h.start)}・${h.speaker === "client" ? "個案" : "心理師"}`),
        el("a", { href: "#", onclick: (ev) => { ev.preventDefault(); openSession(h.session_id, h.segment_id); } }, h.text),
      )),
    );
  });
  main.replaceChildren(frag);
}

// ---------- session workspace ----------

async function openSession(sid, focusSeg) {
  let r;
  try {
    r = await api(`/api/sessions/${encodeURIComponent(sid)}`);
  } catch (err) {
    document.getElementById("main").replaceChildren(el("div", { class: "empty" }, `無法開啟會談：${err.message}`));
    return;
  }
  renderSession(r, focusSeg);
}

function highlight(ids) {
  document.querySelectorAll(".seg.hl").forEach((s) => s.classList.remove("hl"));
  ids.forEach((id, i) => {
    const seg = document.getElementById(`seg-${id}`);
    if (!seg) return;
    seg.classList.add("hl");
    if (i === 0) seg.scrollIntoView({ block: "center", behavior: "smooth" });
  });
}

function collectNote() {
  const sections = {};
  document.querySelectorAll(".note-section").forEach((sec) => {
    sections[sec.dataset.key] = [...sec.querySelectorAll(".sentence")].map((s) => {
      const text = s.querySelector(".txt").textContent.trim();
      const edited = text !== s.dataset.orig;
      // Only the words, the citations and the therapist's confirmation are sent.
      // The server works out every status itself and ignores one sent from here.
      return {
        text,
        evidence: JSON.parse(s.dataset.evidence),
        source: edited ? "transcript" : (s.dataset.source || "transcript"),
        confirmed_by_therapist: confirmed.has(text),
      };
    }).filter((s) => s.text);
  });
  return { template: currentSession.note.template, sections };
}

function noteEdited() {
  return [...document.querySelectorAll(".note-section .sentence")].some((s) =>
    s.querySelector(".txt").textContent.trim() !== (s.dataset.orig || ""));
}

// High-level risk cues the therapist chose to leave out of the note: segment id -> reason.
const dismissed = new Map();

function openRiskCues() {
  return (currentSession.risk_uncovered || []).filter((u) => !dismissed.has(u.segment_id));
}

function dismissCue(segmentId) {
  const reason = prompt(`不把 #${segmentId} 的風險線索寫進紀錄的理由（會寫入稽核紀錄）`, "");
  if (!reason || reason.trim().length < 2) return;
  dismissed.set(segmentId, reason.trim());
  renderRiskGate();
  if (noteEdited()) reverify(); else rerenderNote(); // keeps what the therapist is typing
}

function renderRiskGate() {
  const box = document.getElementById("risk-gate");
  if (!box) return;
  const locked = !!currentSession.signed;
  const open = locked ? [] : openRiskCues();
  const left = locked ? (currentSession.risk_dismissals || []) : [...dismissed].map(([segment_id, reason]) => ({ segment_id, reason }));
  box.replaceChildren(
    ...open.map((u) => el("div", { class: "gate-item" },
      el("span", {}, `#${u.segment_id} 的風險線索（${u.category}）還沒有寫進紀錄：請補寫並引用該段，或註明不寫的理由。`),
      el("button", { class: "confirm", onclick: () => dismissCue(u.segment_id) }, "不納入紀錄（填理由）"))),
    ...left.map((d) => el("div", { class: "gate-item done" }, `#${d.segment_id} 未納入紀錄，理由：${d.reason}`)),
  );
}

// Flagged sentences the therapist has checked and kept as written.
const confirmed = new Set();

function sentenceRow(s) {
  const flagged = s.status === "weak" || s.status === "unsupported";
  const locked = !!currentSession.signed;
  const isMeasure = s.source === "measure";
  const isConfirmed = flagged && (locked ? !!s.confirmed_by_therapist : confirmed.has(s.text));
  const row = el("div", {
    class: `sentence ${isConfirmed ? "confirmed" : s.status}`,
    "data-evidence": JSON.stringify(s.evidence),
    "data-status": s.status,
    "data-orig": s.text,
    "data-support": s.support ?? 0,
    "data-reason": s.reason || "",
    "data-source": s.source || "transcript",
    title: isMeasure ? "由量表資料自動填入，不能修改" : (STATUS_NAMES[s.status] || ""),
  },
    el("div", { class: "body" },
      // Score lines come from the questionnaire data and a signed note is the record: neither is editable.
      el("span", { class: "txt", contenteditable: locked || isMeasure ? "false" : "true", onclick: () => highlight(s.evidence), onfocus: () => highlight(s.evidence) }, s.text),
      flagged ? el("div", { class: "reason" },
        isConfirmed ? "心理師已確認" : s.reason,
        isConfirmed || locked ? null : el("button", { class: "confirm", onclick: () => { confirmed.add(s.text); reverify(); } }, "確認無誤"),
      ) : null,
    ),
    el("span", { class: "ev", onclick: () => highlight(s.evidence) }, s.source === "measure" ? "量表" : s.evidence.length ? `#${s.evidence.join(", #")}` : "無來源"),
  );
  return row;
}

function rerenderNote() {
  renderNote(document.querySelector(".note-section").parentElement, currentSession.note, currentSession.verification);
}

function blockingCount(note) {
  return Object.values(note.sections).flat().filter((s) => (s.status === "unsupported" || s.must_confirm || s.status === "unchecked") && !confirmed.has(s.text)).length;
}

function renderNote(container, note, verification) {
  container.replaceChildren(
    ...Object.entries(note.sections).map(([key, items]) => el("div", { class: "note-section", "data-key": key },
      el("h4", {}, SECTION_NAMES[key] || key),
      SECTION_HINTS[key] && !currentSession.signed ? el("div", { class: "section-hint" }, SECTION_HINTS[key]) : null,
      items.length ? items.map(sentenceRow)
        : currentSession.signed ? el("div", { class: "sentence empty-section" }, "（無）")
        : el("div", { class: "sentence", "data-evidence": "[]", "data-orig": "" }, el("span", { class: "txt", contenteditable: "true" }, "")),
    )),
  );
  const bar = document.getElementById("verify-summary");
  const counts = `${verification.supported}/${verification.total} 句用字與引用段落相符` +
    (verification.weak ? `，${verification.weak} 句支持不足` : "") +
    (verification.unsupported ? `，${verification.unsupported} 句無支持證據` : "");
  if (currentSession.signed) {
    bar.textContent = `簽核時的驗證結果：${counts}`;
    return;
  }
  const blocking = blockingCount(note);
  const cues = openRiskCues().length;
  bar.textContent = `驗證 agent：${counts}` +
    (blocking ? `（尚有 ${blocking} 句需修改、刪除或確認才能簽核）` : "") +
    (cues ? `（尚有 ${cues} 則風險線索未寫入紀錄）` : "") +
    (verification.total === 0 ? "（紀錄是空的，不能簽核）" : "");
  document.getElementById("sign-btn").disabled = signBlocked();
}

function signBlocked() {
  return blockingCount(currentSession.note) > 0 || openRiskCues().length > 0 || currentSession.verification.total === 0;
}

function renderSession(r, focusSeg) {
  currentSession = r;
  confirmed.clear(); // confirmations belong to one note
  dismissed.clear();
  const locked = !!r.signed;
  const main = document.getElementById("main");
  const riskSegs = new Set(r.risk.flags.map((f) => f.segment_id));

  const transcript = el("section", { class: "card transcript" },
    el("h3", {}, "逐字稿 ", el("small", {}, "Transcript")),
    r.transcript.map((s) => el("div", { class: `seg${riskSegs.has(s.id) ? " risk" : ""}`, id: `seg-${s.id}` },
      el("span", { class: "t" }, `#${s.id} ${fmtTime(s.start)}`),
      el("span", { class: `who ${s.speaker}`, title: s.speaker_source === "model" ? "由本機模型依內容推測，請確認" : "" },
        (s.speaker === "client" ? "個案" : s.speaker === "therapist" ? "心理師" : "說話者") + (s.speaker_source === "model" ? "?" : "")),
      el("span", {}, s.text),
    )),
  );

  const risk = r.risk;
  const riskPanel = el("div", { class: `risk-panel lvl-${risk.level}` },
    el("h4", {}, `風險線索：${RISK_NAMES[risk.level]}`),
    risk.flags.map((f) => el("div", { class: "flag", onclick: () => highlight([f.segment_id]) },
      el("b", {}, `[${f.category}]`), `#${f.segment_id}「${f.quote}」`, f.negated ? "（含否定語，請確認）" : "",
      f.speaker_unconfirmed ? "（說話者未確認，可能是心理師的提問）" : "")),
    risk.protective.length ? el("div", { class: "flag" }, el("b", {}, "[保護因子]"),
      risk.protective.map((p) => `#${p.segment_id}「${p.quote}」`).join(" ")) : null,
    risk.flags.length ? el("div", { class: "checks" },
      el("span", {}, risk.screening_asked.length ? `✓ 逐字稿出現自殺意念詢問用語（#${risk.screening_asked.join(", #")}）` : "✗ 逐字稿中未見自殺意念詢問"),
      el("span", {}, risk.safety_actions.length ? `✓ 逐字稿出現安全計畫或轉介用語（#${risk.safety_actions.join(", #")}）` : "✗ 未見安全計畫或轉介"),
    ) : null,
    risk.checklist.length ? el("div", { class: "checklist" },
      el("div", { class: "checklist-title" }, "自殺風險評估要素（關鍵詞比對，只看是否談到，無法評估評估品質）"),
      risk.checklist.map((c) => el("span", { class: c.covered.length ? "done" : "missing" },
        c.covered.length ? `✓ ${c.item}（#${c.covered.join(", #")}）` : `○ ${c.item}：可考慮補問或補記`)),
    ) : null,
    el("div", { class: "disclaimer" }, "提示僅供參考，不取代心理師的臨床判斷；未標示不代表沒有風險。上傳錄音的說話者由模型推測，只有逐字稿標示的心理師用語才計入詢問與安全措施。"),
  );

  const noteBox = el("div", {});
  const notePanel = el("section", { class: `card${locked ? " locked" : ""}` },
    locked
      ? el("h3", {}, `已簽核紀錄（${r.note.template}）`, el("small", {}, "唯讀；更正請另寫補充說明 Signed — read-only"))
      : el("h3", {}, `紀錄草稿（${r.note.template}）`, el("small", {}, "Draft note — edit before signing")),
    riskPanel,
    el("div", { id: "risk-gate" }),
    noteBox,
    el("div", { class: "verify-bar" },
      el("span", { id: "verify-summary" }),
      locked ? null : el("div", { class: "actions" },
        el("button", { onclick: addTestSentence, title: "加入一句逐字稿中沒有的內容，示範驗證 agent 會抓出來" }, "加入測試句"),
        el("button", { onclick: () => reverify() }, "重新驗證"),
        el("button", { class: "primary", id: "sign-btn", onclick: sign }, "確認並簽核"),
      ),
    ),
    el("div", { id: "sign-status", role: "status" }),
    locked ? signedBox(r) : null,
  );

  const head = el("div", { class: "session-head" },
    el("div", {},
      el("button", { class: "back", onclick: () => openClient(r.client_id) }, "← 回個案"),
      el("h2", {}, `${r.session_id}・第 ${r.session_no} 次會談・${r.date}`),
    ),
    el("div", { class: "timings" },
      Object.entries(r.timings_ms).map(([k, v]) => el("span", {}, `${AGENT_NAMES[k] || k} ${v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${v} ms`}`)),
      el("span", {}, r.engine),
    ),
  );

  // How the draft was made, when it matters: the model did not answer and the rule engine wrote it.
  const warnings = (r.warnings || []).length && !locked
    ? el("div", { class: "warnings", role: "alert" }, r.warnings.map((w) => el("div", {}, w))) : null;
  main.replaceChildren(head, warnings || "", el("div", { class: "workspace" }, transcript, notePanel));
  renderRiskGate();
  renderNote(noteBox, r.note, r.verification);
  if (focusSeg) highlight([focusSeg]);
  noteBox.dataset.ready = "1";
}

function showMessage(text, bad) {
  const box = document.getElementById("sign-status");
  if (box) box.replaceChildren(el("span", { class: bad ? "problem" : "" }, text));
}

// Signature details and the addenda of a signed note. The note above stays as signed.
function signedBox(r) {
  const sig = r.signature;
  const list = el("div", { class: "addenda" });
  const draw = (items) => list.replaceChildren(...items.map((a) => el("div", { class: "addendum" },
    el("div", { class: "meta" }, `補充說明・${a.author}・${fmtDateTime(a.created_at)}`), el("div", {}, a.text))));
  draw(r.addenda || []);
  const form = el("form", { class: "addendum-form" },
    el("textarea", { name: "text", rows: "2", required: true, maxlength: "4000", placeholder: "補充說明（只能新增，不會改動已簽核的紀錄）", "aria-label": "補充說明" }),
    el("input", { type: "text", name: "author", required: true, maxlength: "80", value: sig.signed_by, "aria-label": "姓名" }),
    el("button", { type: "submit" }, "新增補充說明"),
  );
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const out = await api(`/api/sessions/${encodeURIComponent(r.session_id)}/addendum`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: form.text.value, author: form.author.value }),
      });
      draw(out.addenda);
      form.text.value = "";
      showMessage("已新增補充說明。");
    } catch (err) {
      showMessage(`無法新增補充說明：${err.message}`, true);
    }
  });
  return el("div", { class: "signed-box" },
    el("div", { class: "signed" }, `已由 ${sig.signed_by} 於 ${fmtDateTime(sig.signed_at)} 簽核`),
    sig.note_sha256 ? el("div", { class: "hashes", title: "簽核時由伺服器計算，用來核對紀錄與逐字稿之後沒有被改動" },
      `紀錄雜湊 ${sig.note_sha256.slice(0, 16)}…・逐字稿雜湊 ${sig.transcript_sha256.slice(0, 16)}…・驗證規則版本 ${sig.verifier_version}`) : null,
    list, form);
}

async function reverify() {
  let r;
  try {
    r = await api(`/api/sessions/${encodeURIComponent(currentSession.session_id)}/verify`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(collectNote()),
    });
  } catch (err) {
    showMessage(`無法重新驗證：${err.message}`, true);
    if (err.status === 409) openSession(currentSession.session_id); // signed elsewhere: show the record
    return false;
  }
  currentSession.note = r.note;
  currentSession.verification = r.verification;
  currentSession.risk_uncovered = r.risk_uncovered;
  renderRiskGate();
  rerenderNote();
  return true;
}

function addTestSentence() {
  const first = document.querySelector(".note-section");
  const row = sentenceRow({ text: "個案表示與母親關係良好，最近常一起出遊。", evidence: [], status: "unchecked" });
  row.dataset.orig = "";
  first.append(row);
  reverify();
}

let signing = false;

async function sign() {
  if (signing) return;
  signing = true;
  const btn = document.getElementById("sign-btn");
  btn.disabled = true;
  try {
    // The server checks the note again whatever is sent; verifying first shows the
    // therapist the same result before a name is asked for.
    if (noteEdited() && !(await reverify())) return;
    if (signBlocked()) {
      showMessage("紀錄還不能簽核：請先處理標示的句子，以及還沒寫進紀錄的風險線索。", true);
      return;
    }
    const by = prompt("簽核心理師姓名", "王心理師");
    if (!by) return;
    await api(`/api/sessions/${encodeURIComponent(currentSession.session_id)}/sign`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        signed_by: by, note: collectNote(),
        risk_dismissals: [...dismissed].map(([segment_id, reason]) => ({ segment_id, reason })),
      }),
    });
    // Show what the server filed, read-only, rather than what this page had.
    await openSession(currentSession.session_id);
  } catch (err) {
    showMessage(`無法簽核：${err.message}`, true);
    if (err.data && err.data.risk_uncovered) { currentSession.risk_uncovered = err.data.risk_uncovered; renderRiskGate(); }
  } finally {
    signing = false;
    const b = document.getElementById("sign-btn");
    if (b) b.disabled = signBlocked();
  }
}

loadStatus();
loadClients().then(() => {
  // ?session=C001-S04 opens a session directly (handy for demos and screenshots).
  const params = new URLSearchParams(location.search);
  const first = document.querySelector("#client-list li");
  if (params.get("session")) {
    markActive(params.get("session").split("-")[0]);
    openSession(params.get("session"));
  } else if (first) {
    openClient(params.get("client") || first.dataset.id);
  }
});
