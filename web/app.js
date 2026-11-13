"use strict";

// Haven therapist UI. Talks only to the local Haven server (same origin).
// No inline styles or scripts and nothing from another origin: the server's
// Content-Security-Policy would block them.

const SECTION_NAMES = {
  S: "S 主觀資料", O: "O 客觀資料", A: "A 評估", P: "P 計畫", D: "D 資料", R: "R 風險與安全",
};
// Shown under a section title: what the draft cannot contain and the therapist adds.
const SECTION_HINTS = {
  O: "量表分數由系統填入。精神狀態觀察（外觀、情感、思考、定向、風險行為）逐字稿看不出來，請心理師自行補寫。",
  R: "逐字稿中的風險線索、保護因子與安全措施；不受句數限制。提議而未完成的安全計畫會寫成「心理師提議」。",
};
// Describes the cues found in the transcript, not the client's risk level.
const RISK_NAMES = {
  none: "未偵測到風險線索", info: "有背景線索（非個案本人的意念）", review: "有需留意的線索", high: "有自殺或自傷等高關注線索",
  critical: "有需優先確認的線索（計畫或工具、自殺行為、傷害他人或通報義務）",
};
const LEVEL_ORDER = ["critical", "high", "review", "info", "none"];
const LEVEL_SHORT = { critical: "優先確認", high: "高關注", review: "需留意", info: "背景", none: "" };
// Every state has a mark and words, so it never depends on colour alone.
const STATES = {
  supported: { mark: "✓", name: "有逐字稿支持" },
  weak: { mark: "！", name: "支持不足" },
  unsupported: { mark: "✗", name: "未能證實" },
  unchecked: { mark: "？", name: "尚未驗證" },
  dirty: { mark: "✎", name: "已修改，尚未驗證" },
  confirmed: { mark: "✓", name: "已由您確認保留" },
  measure: { mark: "＃", name: "量表分數（系統填入）" },
};
const AGENT_NAMES = { asr: "載入逐字稿", writer: "撰寫", verifier: "查核", risk: "風險", outcome: "成效" };
const SHOWN_PER_GROUP = 3;
const SESSION_ID = /^[A-Za-z0-9-]{1,40}$/;

// ---------- state ----------

let nav = 0;                 // goes up on every navigation; a late response compares and is dropped
let currentClient = null;    // client id shown or last shown
let session = null;          // the session result from the server, or null on the client page
let sentences = {};          // section key -> [sentence state]; the note as the therapist has it now
let nextKey = 1;             // each sentence gets a stable key; confirmations follow the key, not the words
let edited = false;          // something would be lost by leaving this session
let verifying = false;
let verifyAgain = false;
let verifyTimer = null;
let serverStatus = null;
const confirmed = new Set(); // keys of flagged sentences the therapist checked and kept
const keepReasons = new Map(); // key -> what a kept sentence with no citation is based on
const dismissed = new Map(); // segment id -> reason, for high-level risk cues left out of the note

// ---------- small helpers ----------

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

// replaceChildren would print "null" for an absent child; this drops them like el() does.
function put(node, ...children) {
  node.replaceChildren(...children.flat().filter((c) => c != null && c !== false));
}

const HTTP_MESSAGES = {
  400: "送出的資料格式不正確。",
  403: "伺服器拒絕了這個請求。",
  404: "找不到這筆資料。",
  408: "等待逾時，請再試一次。",
  409: "目前的狀態不允許這個操作。",
  413: "送出的內容太大。",
  500: "伺服器發生錯誤，請看終端機的訊息。",
};

async function api(path, opts = {}) {
  // The server refuses any API request without this header (cross-site request protection).
  opts.headers = { ...(opts.headers || {}), "X-Haven": "1" };
  let res, data = {};
  try {
    res = await fetch(path, opts);
  } catch (err) {
    throw new Error("連不上本機的 Haven 伺服器，請確認程式還在執行。");
  }
  try { data = await res.json(); } catch (err) { /* not JSON */ }
  if (!res.ok) {
    // The server sends a Chinese message for the therapist; the English one stays in the console.
    const e = new Error(data.message_zh || HTTP_MESSAGES[res.status] || `操作沒有完成（代碼 ${res.status}）。`);
    e.status = res.status;
    e.data = data;
    if (data.error) console.warn(`Haven ${res.status}: ${data.error}`);
    throw e;
  }
  return data;
}

function post(path, body) {
  return api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
}

let toastTimer = null;
function toast(message) {
  document.getElementById("toast-text").textContent = message;
  document.getElementById("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { document.getElementById("toast").hidden = true; }, 12000);
}
document.getElementById("toast-close").addEventListener("click", () => { document.getElementById("toast").hidden = true; });
window.addEventListener("unhandledrejection", (e) => toast((e.reason && e.reason.message) || "發生錯誤，操作沒有完成。"));

// Disables a button while its request runs and shows how long it has taken, so a
// slow local model is visibly working and a second click cannot start it twice.
async function busy(btn, label, fn) {
  if (!btn) return fn();
  if (btn.getAttribute("aria-busy") === "true") return undefined;
  const old = btn.textContent, wasDisabled = btn.disabled, t0 = Date.now();
  btn.disabled = true;
  btn.setAttribute("aria-busy", "true");
  btn.textContent = label;
  const tick = setInterval(() => { btn.textContent = `${label}（${Math.round((Date.now() - t0) / 1000)} 秒）`; }, 1000);
  try {
    return await fn();
  } finally {
    clearInterval(tick);
    btn.removeAttribute("aria-busy");
    if (btn.isConnected) { btn.textContent = old; btn.disabled = wasDisabled; }
  }
}

function loading(text) {
  const t0 = Date.now();
  const secs = el("span", {}, "");
  const box = el("div", { class: "empty loading", role: "status" }, el("span", { class: "spinner", "aria-hidden": "true" }), text, secs);
  const tick = setInterval(() => {
    if (!box.isConnected) return clearInterval(tick);
    secs.textContent = `（已 ${Math.round((Date.now() - t0) / 1000)} 秒）`;
  }, 1000);
  return box;
}

function failed(text, retry) {
  return el("div", { class: "empty", role: "alert" }, el("p", { class: "problem" }, text), el("button", { type: "button", onclick: retry }, "重試"));
}

function fmtDateTime(iso) {
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString("zh-TW", { dateStyle: "long", timeStyle: "short", hour12: false });
}

function fmtTime(sec) {
  const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function engineName(engine) {
  if (!engine || engine === "rule-based demo") return "規則引擎（未連接語言模型）";
  if (engine.startsWith("規則引擎")) return engine;
  return `本機模型 ${engine.replace(/^(ollama|openai-compat):/, "")}`;
}

function speakerName(s) {
  const name = s.speaker === "client" ? "個案" : s.speaker === "therapist" ? "心理師" : "說話者未標示";
  return name + (s.speaker_source === "model" ? "（推測）" : "");
}

function setStep(n) {
  document.querySelectorAll("#stepper li").forEach((li) => {
    const step = Number(li.dataset.step);
    li.classList.toggle("done", step < n);
    li.classList.toggle("current", step === n);
    if (step === n) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
  });
}

// Leaving a session with edits, confirmations or reasons loses them: the draft
// lives in this page until it is signed.
function leaveOk() {
  if (!session || session.signed || !edited) return true;
  return confirm("這份紀錄還沒簽核。離開後，修改過的句子、已確認保留的句子和不納入紀錄的理由都不會保存。確定離開？");
}
window.addEventListener("beforeunload", (e) => {
  if (session && !session.signed && edited) { e.preventDefault(); e.returnValue = ""; }
});

// ---------- status & client list ----------

async function loadStatus() {
  const box = document.getElementById("status");
  let s;
  try {
    s = await api("/api/status");
  } catch (err) {
    box.replaceChildren(el("span", { class: "pill bad" }, err.message), el("button", { type: "button", onclick: loadStatus }, "重試"));
    return;
  }
  serverStatus = s;
  // Each pill states what the server looked up just now; none is a fixed number.
  const where = (e) => !e.local ? "不是本機或區域網路位址" : e.loopback ? "本機" : "診所區域網路";
  const host = (e) => { try { return new URL(e.url).host; } catch (err) { return e.url; } };
  const pills = [];
  if (s.llm) {
    pills.push(el("span", { class: `pill ${s.llm.local ? "good" : "bad"}`, title: `目前解析到：${s.llm.addresses.join("、") || "無"}` },
      `模型端點 ${host(s.llm)}（${where(s.llm)}）`));
  }
  if (s.asr) {
    pills.push(el("span", { class: `pill ${s.asr.local ? "good" : "bad"}`, title: `目前解析到：${s.asr.addresses.join("、") || "無"}` },
      `轉寫端點 ${host(s.asr)}（${where(s.asr)}）`));
  }
  pills.push(el("span", { class: `pill ${s.refused_connections ? "bad" : ""}`,
    title: "Haven 自己的端點檢查擋下的連線次數（啟動至今）。這不是封包側錄；模型伺服器本身連到哪裡，Haven 看不到。" },
    `已拒絕的非本機連線：${s.refused_connections} 次`));
  pills.push(el("span", { class: "pill" }, `目前引擎：${engineName(s.engine)}`));
  box.replaceChildren(...pills);
}

async function loadClients() {
  const list = document.getElementById("client-list");
  let clients;
  try {
    clients = await api("/api/clients");
  } catch (err) {
    list.replaceChildren(el("li", {}, failed(err.message, () => loadClients().then(() => markActive(currentClient)))));
    return [];
  }
  list.replaceChildren(...clients.map((c) => el("li", { "data-id": c.id },
    el("button", { type: "button", class: "client-btn", onclick: () => { if (leaveOk()) openClient(c.id); } },
      el("span", { class: "who" }, c.alias, el("span", { class: "sub" }, c.presenting_concern)),
      c.alert_count ? el("span", { class: "badge" }, `${c.alert_count} 則提醒`) : null,
    ))));
  markActive(currentClient);
  return clients;
}

function markActive(id) {
  document.querySelectorAll("#client-list li").forEach((li) => {
    const on = li.dataset.id === id;
    li.classList.toggle("active", on);
    const btn = li.querySelector("button");
    if (btn) { if (on) btn.setAttribute("aria-current", "true"); else btn.removeAttribute("aria-current"); }
  });
}

function setSimNote(kind) {
  const box = document.getElementById("sim-note");
  box.className = `sim-note${kind === "real" ? " real" : ""}`;
  box.textContent = kind === "real" ? "含真實個案資料：受個人資料保護法保護，請勿外流或截圖分享。"
    : kind === "simulated" ? "目前顯示的是模擬會談，非真實個案。"
      : "選擇個案後，這裡會顯示資料是模擬會談還是真實個案。";
}

// ---------- client view ----------

function chart(m) {
  const w = 220, h = 104, padX = 16, padTop = 20, padBottom = 18;
  const pts = m.history;
  const xs = (i) => padX + (pts.length === 1 ? 0 : (i * (w - 2 * padX)) / (pts.length - 1));
  const ys = (v) => h - padBottom - (v / m.max) * (h - padTop - padBottom);
  const tone = m.status === "deteriorated" ? "bad" : m.status === "not_on_track" ? "warn" : ["improved", "recovered"].includes(m.status) ? "good" : "accent";
  const ns = "http://www.w3.org/2000/svg";
  const make = (tag, attrs, text) => {
    const n = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text != null) n.textContent = text;
    return n;
  };
  const svg = make("svg", { viewBox: `0 0 ${w} ${h}`, role: "img", class: `tone-${tone}`,
    "aria-label": `${m.name}：${pts.map((p) => `第 ${p.session} 次 ${p.score} 分`).join("、")}；臨床切點 ${m.clinical_cutoff} 分` });
  if (m.clinical_cutoff != null) {
    const y = ys(m.clinical_cutoff);
    svg.append(make("line", { x1: padX, x2: w - padX, y1: y, y2: y, class: "cutoff" }),
      make("text", { x: w - padX, y: y - 3, "text-anchor": "end", class: "cutoff-label" }, `臨床切點 ${m.clinical_cutoff}`));
  }
  svg.append(make("polyline", { points: pts.map((p, i) => `${xs(i)},${ys(p.score)}`).join(" "), class: "trend" }));
  pts.forEach((p, i) => {
    const dot = make("circle", { cx: xs(i), cy: ys(p.score), r: "3.5", class: "dot" });
    dot.append(make("title", {}, `第 ${p.session} 次（${p.date || ""}）：${p.score} 分`));
    svg.append(dot,
      make("text", { x: xs(i), y: ys(p.score) - 7, "text-anchor": "middle", class: "score" }, p.score),
      make("text", { x: xs(i), y: h - 4, "text-anchor": "middle", class: "tick" }, `第${p.session}次`));
  });
  return el("div", { class: "chart" },
    el("div", { class: "title" }, el("span", {}, m.name), el("span", {}, `${m.latest}／${m.max}（${m.band}）`)),
    svg,
    m.note ? el("div", { class: "chart-note" }, m.note) : null,
  );
}

function sessionLabel(m) {
  if (m.missing) return `${m.session_id}（找不到逐字稿）`;
  const state = m.signed ? "已簽核" : m.processed ? "待簽核" : "尚未產生紀錄";
  return `第 ${m.session_no} 次・${m.date}・${state}`;
}

async function openClient(id) {
  const my = ++nav;
  session = null;
  edited = false;
  currentClient = id;
  markActive(id);
  setStep(1);
  const main = document.getElementById("main");
  main.replaceChildren(loading("載入個案資料…"));
  let brief;
  try {
    brief = await api(`/api/clients/${encodeURIComponent(id)}/brief`);
  } catch (err) {
    if (my !== nav) return;
    main.replaceChildren(failed(`無法載入個案：${err.message}`, () => openClient(id)));
    return;
  }
  if (my !== nav) return; // the therapist has moved on; this answer is for an old page
  const frag = document.getElementById("tpl-client").content.cloneNode(true);
  const c = brief.client;
  frag.querySelector(".client-name").textContent = `${c.alias}・${c.age} 歲`;
  frag.querySelector(".concern").textContent = `主訴：${c.presenting_concern}`;
  const meta = brief.sessions_meta || [];
  setSimNote(meta.some((m) => m.simulated === false) ? "real" : "simulated");

  const alerts = brief.outcome.alerts;
  frag.querySelector(".alerts").append(...(alerts.length
    ? alerts.map((a) => el("div", { class: `alert ${a.status}` }, el("b", {}, `${a.label || "提醒"}　`), `${a.name}：${a.message}`))
    : [el("div", { class: "alert ok" }, "量表追蹤：目前沒有提醒")]));
  // One prompt for all not-improving measures, so it is read rather than skimmed.
  const review = alerts.find((a) => a.review);
  if (review) frag.querySelector(".alerts").append(el("div", { class: "review" }, `建議：${review.review}`));
  frag.querySelector(".charts").append(...brief.outcome.measures.map(chart));

  const plan = frag.querySelector(".last-plan");
  if ((brief.not_processed || []).length) {
    plan.append(el("div", { class: "review" }, `較新的會談（${brief.not_processed.join("、")}）還沒有產生紀錄，以下摘要不包含它們。`));
  }
  if (brief.last_session) {
    const ls = brief.last_session;
    plan.append(
      el("div", {}, `最近一次有紀錄的會談：第 ${ls.session_no} 次（${ls.date}），風險線索：${RISK_NAMES[ls.risk_level] ?? ls.risk_level}`),
      brief.plan.length ? el("div", { class: "plan-title" }, "上次計畫（已簽核的紀錄，或草稿中通過查核的句子）：") : null,
      brief.plan.length ? el("ul", {}, brief.plan.map((p) => el("li", {}, p))) : null,
    );
  }

  frag.querySelector(".session-buttons").append(...meta.map((m) =>
    el("button", { type: "button", title: m.session_id, disabled: !!m.missing,
      onclick: (e) => openSession(m.session_id, null, e.currentTarget) }, sessionLabel(m))));

  const upForm = frag.querySelector(".upload-form");
  const upMsg = frag.querySelector(".upload-msg");
  const numbers = meta.map((m) => m.session_no || 0);
  upForm.session_id.value = `${id}-S${String(Math.max(0, ...numbers) + 1).padStart(2, "0")}`;
  upForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = upForm.audio.files[0];
    const btn = upForm.querySelector("button[type=submit]");
    upMsg.className = "upload-msg";
    upMsg.textContent = "本機轉寫與產生紀錄中，請不要關閉這個頁面。長錄音需要幾分鐘。";
    await busy(btn, "轉寫中", async () => {
      try {
        const q = new URLSearchParams({ client: id, session_id: upForm.session_id.value, consent: upForm.consent.checked ? "1" : "0", simulated: upForm.simulated.checked ? "1" : "0" });
        const r = await api(`/api/upload?${q}`, { method: "POST", headers: { "X-Filename": encodeURIComponent(file.name) }, body: file });
        await loadClients();
        markActive(id);
        if (my !== nav) { // the therapist went elsewhere while it ran: say so, do not take the screen
          toast(`${r.session_id} 已轉寫完成，可以從個案頁開啟。`);
          return;
        }
        upMsg.textContent = "完成。Haven 不保存錄音，暫存檔已刪除。";
        ++nav;
        renderSession(r);
      } catch (err) {
        upMsg.className = "upload-msg problem";
        upMsg.textContent = `沒有完成：${err.message}`;
      }
    });
  });

  const askForm = frag.querySelector(".ask-form");
  const askOut = frag.querySelector(".ask-result");
  askForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    await busy(askForm.querySelector("button"), "查詢中", async () => {
      let r;
      try {
        // POST: the question is not put in the URL, and asking the model is not a read.
        r = await post(`/api/clients/${encodeURIComponent(id)}/ask`, { q: askForm.q.value });
      } catch (err) {
        askOut.replaceChildren(el("p", { class: "problem" }, `查詢沒有完成：${err.message}`));
        return;
      }
      if (my !== nav) return;
      put(askOut, askResult(r));
    });
  });
  main.replaceChildren(frag);
  main.querySelector(".client-name").focus({ preventScroll: true });
}

function askResult(r) {
  const out = [];
  if (r.answer) out.push(el("p", {}, r.answer));
  if (!r.hits.length) {
    // Keyword search: finding nothing is not evidence that it was never discussed.
    out.push(el("p", {}, "關鍵詞沒有比對到片段。這不代表會談中沒有談過，請換個說法再查，或直接看逐字稿。"));
    return out;
  }
  const groups = r.sessions || [];
  if (groups.length) {
    out.push(el("p", { class: "ask-summary" },
      `共 ${r.total} 段，出現在 ${groups.length} 次會談：` + groups.map((g) => `第 ${g.session_no} 次（${g.count} 段）`).join("、") +
      (r.total > r.hits.length ? `。以下每次會談各列出最相關的幾段。` : "。")));
    if (r.expanded && r.expanded.length) out.push(el("p", { class: "flag-note" }, `同時查了這些說法：${r.expanded.join("、")}`));
  }
  const bySession = new Map();
  for (const h of r.hits) {
    if (!bySession.has(h.session_id)) bySession.set(h.session_id, []);
    bySession.get(h.session_id).push(h);
  }
  for (const [sid, hits] of bySession) {
    const g = groups.find((x) => x.session_id === sid);
    out.push(el("div", { class: "hit-group" },
      el("div", { class: "hit-head" }, `第 ${hits[0].session_no} 次會談` + (g && g.count > hits.length ? `（共 ${g.count} 段，顯示 ${hits.length} 段）` : "")),
      hits.map((h) => el("div", { class: "hit" },
        el("div", { class: "meta" }, `${fmtTime(h.start)}・${speakerName(h)}`),
        el("button", { type: "button", class: "link", onclick: (e) => openSession(h.session_id, h.segment_id, e.currentTarget) }, h.text)))));
  }
  return out;
}

// ---------- session workspace ----------

async function openSession(sid, focusSeg, btn) {
  if (!SESSION_ID.test(sid)) {
    document.getElementById("main").replaceChildren(el("div", { class: "empty", role: "alert" }, "會談編號的格式不正確。"));
    return;
  }
  const my = ++nav;
  const main = document.getElementById("main");
  const work = async () => {
    // POST: opening a session may draft its note, which a GET must never do.
    const r = await post(`/api/sessions/${encodeURIComponent(sid)}/open`);
    if (my !== nav) return; // a slower answer for a session the therapist has left
    renderSession(r, focusSeg);
  };
  try {
    if (btn && btn.isConnected) {
      await busy(btn, "開啟中，未處理過的會談要等本機模型產生紀錄", work);
    } else {
      main.replaceChildren(loading("開啟會談；沒處理過的會談要等本機模型產生紀錄…"));
      await work();
    }
  } catch (err) {
    if (my !== nav) return;
    main.replaceChildren(failed(`無法開啟會談：${err.message}`, () => openSession(sid, focusSeg)),
      el("button", { type: "button", class: "back", onclick: () => openClient(currentClient || sid.split("-")[0]) }, "← 回個案"));
  }
}

// Scrolls the transcript column only. scrollIntoView would move the whole page
// and carry the sentence being edited off the screen.
function highlight(ids, scroll = true) {
  document.querySelectorAll(".seg.hl").forEach((s) => s.classList.remove("hl"));
  const box = document.querySelector(".transcript-lines");
  ids.forEach((id, i) => {
    const seg = document.getElementById(`seg-${id}`);
    if (!seg) return;
    seg.classList.add("hl");
    if (i === 0 && scroll && box) {
      const top = seg.offsetTop - box.offsetTop - box.clientHeight / 2 + seg.clientHeight / 2;
      box.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    }
  });
}

// ----- the note as state -----

function adoptNote(note) {
  sentences = {};
  for (const [key, items] of Object.entries(note.sections)) {
    sentences[key] = items.map((s) => ({ ...s, key: nextKey++, verifiedText: s.text }));
  }
}

function allSentences() {
  return Object.values(sentences).flat();
}

function isDirty(s) {
  return s.text.trim() !== (s.verifiedText || "").trim();
}

function isBlocking(s) {
  if (s.source === "measure" || !s.text.trim() || isDirty(s)) return false;
  return (s.status === "unsupported" || s.must_confirm || !["supported", "weak", "unsupported"].includes(s.status)) && !confirmed.has(s.key);
}

function counts() {
  const claims = allSentences().filter((s) => s.source !== "measure" && s.text.trim());
  const clean = claims.filter((s) => !isDirty(s));
  return {
    total: claims.length,
    dirty: claims.length - clean.length,
    supported: clean.filter((s) => s.status === "supported").length,
    weak: clean.filter((s) => s.status === "weak").length,
    unsupported: clean.filter((s) => s.status === "unsupported").length,
    blocking: clean.filter(isBlocking).length,
    kept: clean.filter((s) => confirmed.has(s.key) && (s.status === "weak" || s.status === "unsupported")).length,
  };
}

// Reads what is typed into the page back into the state, so a redraw never loses it.
function syncFromDom() {
  document.querySelectorAll(".note-section .sentence[data-key]").forEach((row) => {
    const s = allSentences().find((x) => String(x.key) === row.dataset.key);
    const txt = row.querySelector(".txt");
    if (s && txt && txt.isContentEditable) s.text = txt.textContent;
  });
}

function notePayload() {
  // Only the words, the citations and the therapist's confirmation are sent.
  // The server works out every status itself and ignores one sent from here.
  const sections = {}, keys = {}, texts = new Map();
  for (const [key, items] of Object.entries(sentences)) {
    const sent = items.filter((s) => s.text.trim());
    keys[key] = sent.map((s) => s.key);
    sections[key] = sent.map((s) => {
      texts.set(s.key, s.text.trim());
      return {
        text: s.text.trim(), evidence: s.evidence,
        source: isDirty(s) ? "transcript" : (s.source || "transcript"),
        confirmed_by_therapist: confirmed.has(s.key) && !isDirty(s),
        keep_reason: confirmed.has(s.key) && !isDirty(s) ? (keepReasons.get(s.key) || "") : "",
      };
    });
  }
  return { payload: { template: session.note.template, sections }, keys, texts };
}

function openRiskCues() {
  return (session.risk_uncovered || []).filter((u) => !dismissed.has(u.segment_id));
}

function signBlocked() {
  const c = counts();
  return verifying || c.dirty > 0 || c.blocking > 0 || openRiskCues().length > 0 || c.total === 0;
}

// ----- drawing the note -----

// Note sentences are plain text. "plaintext-only" keeps pasted markup out of the
// page where the browser supports it; the paste handler does the same everywhere.
const EDITABLE = (() => {
  const probe = document.createElement("span");
  try { probe.contentEditable = "plaintext-only"; } catch (err) { return "true"; }
  return probe.contentEditable === "plaintext-only" ? "plaintext-only" : "true";
})();

function pastePlain(e) {
  e.preventDefault();
  const text = (e.clipboardData || window.clipboardData).getData("text/plain").replace(/\s*\n\s*/g, " ");
  const sel = window.getSelection();
  if (!sel.rangeCount) return;
  sel.deleteFromDocument();
  sel.getRangeAt(0).insertNode(document.createTextNode(text));
  sel.collapseToEnd();
  e.target.dispatchEvent(new Event("input", { bubbles: true }));
}

function rowState(s) {
  const locked = !!session.signed;
  if (s.source === "measure") return "measure";
  if (!locked && isDirty(s)) return "dirty";
  const flagged = s.status === "weak" || s.status === "unsupported";
  if (flagged && (locked ? !!s.confirmed_by_therapist : confirmed.has(s.key))) return "confirmed";
  return STATES[s.status] ? s.status : "unchecked";
}

function stateName(s, state) {
  if (state === "unsupported" && !(s.evidence || []).length) return "沒有引用逐字稿";
  return STATES[state].name;
}

function badge(s, state) {
  return el("span", { class: "st", title: stateName(s, state) },
    el("span", { "aria-hidden": "true" }, STATES[state].mark), el("span", { class: "st-name" }, stateName(s, state)));
}

function sentenceRow(sectionKey, s) {
  const locked = !!session.signed;
  const state = rowState(s);
  const isMeasure = s.source === "measure";
  const editable = !locked && !isMeasure;
  const flagged = (s.status === "weak" || s.status === "unsupported") && state !== "dirty";
  const reasonId = `reason-${s.key}`;
  const row = el("div", { class: `sentence ${state}${s.text.trim() ? "" : " blank"}`, "data-key": s.key });
  const txt = el("span", {
    class: "txt", contenteditable: editable ? EDITABLE : "false",
    role: editable ? "textbox" : null, "aria-multiline": editable ? "false" : null,
    "aria-label": editable ? `${SECTION_NAMES[sectionKey] || sectionKey} 的紀錄句子，可以修改` : null,
    "aria-describedby": flagged ? reasonId : null,
    "data-placeholder": editable ? "（點這裡輸入句子；新句子沒有引用逐字稿，保留時要寫下依據）" : null,
    onpaste: editable ? pastePlain : null,
    onclick: () => highlight(s.evidence),
    onfocus: () => highlight(s.evidence, false),
    oninput: () => onEdit(s, row),
    onblur: () => { if (editable && isDirty(s)) scheduleVerify(); },
    onkeydown: (e) => { if (e.key === "Enter") { e.preventDefault(); e.target.blur(); } },
  }, s.text);
  const reason = flagged ? el("div", { class: "reason", id: reasonId },
    state === "confirmed" ? `已由您確認保留。原因：${s.reason}` : s.reason,
    state === "confirmed" && (locked ? s.keep_reason : keepReasons.get(s.key))
      ? el("div", {}, `依據：${locked ? s.keep_reason : keepReasons.get(s.key)}`) : null,
    state === "confirmed" || locked ? null
      : el("button", { type: "button", class: "confirm", onclick: () => keep(s) },
        (s.evidence || []).length ? "保留此句（我已核對）" : "保留此句（寫下依據）"),
  ) : null;
  row.append(
    badge(s, state),
    el("div", { class: "body" }, txt, reason,
      state === "dirty" ? el("div", { class: "reason" }, "這句修改過，離開輸入框後會自動重新驗證。") : null),
    el("div", { class: "side" },
      isMeasure ? el("span", { class: "ev-none" }, "量表")
        : (s.evidence || []).length
          ? el("button", { type: "button", class: "ev", title: "在逐字稿中標出引用的段落", onclick: () => highlight(s.evidence) }, `#${s.evidence.join(", #")}`)
          : el("span", { class: "ev-none" }, "無引用"),
      editable ? el("button", { type: "button", class: "del", "aria-label": "刪除這一句", title: "刪除這一句", onclick: () => removeSentence(sectionKey, s) }, "刪除") : null,
    ),
  );
  return row;
}

// Typing changes one row in place (the caret must not move); nothing is rebuilt.
function onEdit(s, row) {
  const txt = row.querySelector(".txt");
  s.text = txt.textContent;
  edited = true;
  confirmed.delete(s.key); // a confirmation was for the words as they were
  keepReasons.delete(s.key);
  const dirty = isDirty(s);
  if (dirty && !row.classList.contains("dirty")) {
    row.className = "sentence dirty";
    row.querySelector(".st").replaceWith(badge(s, "dirty"));
    row.querySelectorAll(".reason").forEach((r) => r.remove());
    row.querySelector(".body").append(el("div", { class: "reason" }, "這句修改過，離開輸入框後會自動重新驗證。"));
  }
  row.classList.toggle("blank", !s.text.trim());
  renderSummary();
  // Leaving the box verifies at once; so does a pause in typing (focus and caret are kept).
  clearTimeout(verifyTimer);
  if (dirty) verifyTimer = setTimeout(() => reverify(), 2500);
}

function keep(s) {
  syncFromDom();
  if (isDirty(s)) { // confirm what was checked, not what is half typed
    showMessage("這句剛修改過，先重新驗證；如果仍被標示，再按一次「保留此句」。", true);
    reverify();
    return;
  }
  if (!(s.evidence || []).length) {
    askReason("保留沒有引用的句子", `「${s.text.trim()}」`, "這句的依據（例如：會談中觀察到的非語言行為、會談外取得的資訊）。會存進簽核紀錄和稽核紀錄。", (reason) => {
      keepReasons.set(s.key, reason);
      confirmed.add(s.key);
      edited = true;
      renderNote();
      focusNextBlocking(false);
    });
    return;
  }
  confirmed.add(s.key);
  edited = true;
  renderNote();
  focusNextBlocking(false);
}

function addSentence(sectionKey) {
  syncFromDom();
  const s = { key: nextKey++, text: "", verifiedText: "", evidence: [], status: "unchecked", source: "transcript", reason: "" };
  sentences[sectionKey].push(s);
  edited = true;
  renderNote();
  const row = document.querySelector(`.sentence[data-key="${s.key}"] .txt`);
  if (row) row.focus();
}

function removeSentence(sectionKey, s) {
  syncFromDom();
  if (s.text.trim() && !confirm(`刪除這一句？\n\n${s.text.trim()}`)) return;
  sentences[sectionKey] = sentences[sectionKey].filter((x) => x.key !== s.key);
  confirmed.delete(s.key);
  edited = true;
  renderNote();
  // A deleted sentence may have been the only one citing a risk line: ask the server again.
  reverify();
}

function addTestSentence() {
  syncFromDom();
  const first = Object.keys(sentences)[0];
  sentences[first].push({ key: nextKey++, text: "個案表示與母親關係良好，最近常一起出遊。", verifiedText: "", evidence: [], status: "unchecked", source: "transcript", reason: "" });
  edited = true;
  renderNote();
  reverify();
}

function focusNextBlocking(scroll = true) {
  const next = allSentences().find(isBlocking);
  if (!next) return;
  const row = document.querySelector(`.sentence[data-key="${next.key}"]`);
  if (!row) return;
  if (scroll) row.scrollIntoView({ block: "center", behavior: "smooth" });
  row.querySelector(".txt").focus({ preventScroll: !scroll });
}

function caretOffset(node) {
  const sel = window.getSelection();
  if (!sel.rangeCount || !node.contains(sel.anchorNode)) return null;
  const range = document.createRange();
  range.selectNodeContents(node);
  range.setEnd(sel.anchorNode, sel.anchorOffset);
  return range.toString().length;
}

function renderNote() {
  const box = document.getElementById("note-box");
  if (!box || !session) return;
  // Keep the keyboard where it was: a redraw must not drop focus or the caret.
  const active = document.activeElement && document.activeElement.closest ? document.activeElement.closest(".sentence[data-key]") : null;
  const activeKey = active ? active.dataset.key : null;
  const offset = active ? caretOffset(active.querySelector(".txt")) : null;
  const locked = !!session.signed;
  box.replaceChildren(
    ...Object.entries(sentences).map(([key, items]) => el("div", { class: "note-section", "data-key": key },
      el("div", { class: "section-head" },
        el("h4", {}, SECTION_NAMES[key] || key),
        locked ? null : el("button", { type: "button", class: "add", onclick: () => addSentence(key) }, "＋ 新增句子")),
      SECTION_HINTS[key] && !locked ? el("div", { class: "section-hint" }, SECTION_HINTS[key]) : null,
      items.length ? items.map((s) => sentenceRow(key, s)) : el("div", { class: "sentence empty-section" }, locked ? "（無）" : "（這一欄目前沒有句子）"),
    )),
  );
  if (activeKey) {
    const txt = document.querySelector(`.sentence[data-key="${activeKey}"] .txt`);
    if (txt && txt.isContentEditable) {
      txt.focus({ preventScroll: true });
      if (offset != null && txt.firstChild) {
        const sel = window.getSelection();
        sel.collapse(txt.firstChild, Math.min(offset, txt.firstChild.length));
      }
    }
  }
  renderSummary();
}

// A demo notice names the planted sentence in 「」; once it is fixed or deleted the notice goes.
function demoQuote(w) {
  const m = w.startsWith("示範用：") ? w.match(/「([^」]+)」/) : null;
  return m ? m[1] : null;
}

function renderDemoNotices() {
  const box = document.getElementById("warnings");
  if (!box) return;
  const texts = new Set(allSentences().map((s) => s.text.trim()));
  box.querySelectorAll("[data-quote]").forEach((d) => { d.hidden = !texts.has(d.dataset.quote); });
  box.hidden = ![...box.children].some((d) => !d.hidden);
}

function renderSummary() {
  if (!session) return;
  renderDemoNotices();
  const c = counts();
  const counter = document.getElementById("verify-counter");
  const bar = document.getElementById("verify-summary");
  const who = session.signed ? "已簽核紀錄" : "AI 草稿";
  if (counter) {
    put(counter,
      el("span", { class: "n" }, `${who} ${c.total} 句`),
      el("span", { class: "n good" }, `✓ ${c.supported} 句有逐字稿支持`),
      c.weak ? el("span", { class: "n warn" }, `！ ${c.weak} 句支持不足`) : null,
      c.unsupported ? el("span", { class: "n bad" }, `✗ ${c.unsupported} 句未能證實`) : null,
      c.dirty ? el("span", { class: "n" }, `✎ ${c.dirty} 句已修改待驗證`) : null,
      !session.signed && c.blocking ? el("span", { class: "n bad strong" }, `${c.blocking} 句被攔下，擋住簽核`) : null,
    );
  }
  if (!bar) return;
  if (session.signed) {
    bar.textContent = "以上是簽核時的查核結果。";
    setStep(5);
    return;
  }
  const cues = openRiskCues().length;
  const parts = [];
  if (verifying) parts.push("重新驗證中…");
  if (c.total === 0) parts.push("紀錄是空的，不能簽核。");
  if (c.dirty) parts.push(`有 ${c.dirty} 句修改過，要重新驗證後才能簽核。`);
  if (c.blocking) parts.push(`還差 ${c.blocking} 句：請修改、刪除，或按「保留此句」。`);
  if (cues) parts.push(`還有 ${cues} 則風險線索沒有寫進紀錄。`);
  if (!parts.length) parts.push(c.kept ? `可以簽核（其中 ${c.kept} 句是您確認保留的標示句）。` : "每一句都通過查核，可以簽核。");
  bar.textContent = parts.join(" ");
  const blocked = signBlocked();
  const signBtn = document.getElementById("sign-btn");
  if (signBtn && signBtn.getAttribute("aria-busy") !== "true") signBtn.disabled = blocked;
  const nextBtn = document.getElementById("next-btn");
  if (nextBtn) nextBtn.hidden = c.blocking === 0;
  setStep(blocked ? 3 : 4);
}

// ----- risk panel -----

function askReason(title, quote, label, done) {
  const dlg = document.getElementById("reason-dialog");
  const form = document.getElementById("reason-form");
  document.getElementById("reason-title").textContent = title;
  document.getElementById("reason-quote").textContent = quote;
  document.getElementById("reason-label").textContent = label;
  form.reason.value = "";
  form.onsubmit = (e) => {
    e.preventDefault();
    const reason = form.reason.value.trim();
    if (reason.length < 2) return;
    dlg.close();
    done(reason);
  };
  document.getElementById("reason-cancel").onclick = () => dlg.close();
  dlg.showModal();
}

function dismissCue(u) {
  askReason("不納入紀錄的理由", `#${u.segment_id}（${u.category}）「${u.quote}」`, "理由（會寫入稽核紀錄）", (reason) => {
    dismissed.set(u.segment_id, reason);
    edited = true;
    renderRiskGate();
    renderSummary();
  });
}

function renderRiskGate() {
  const box = document.getElementById("risk-gate");
  if (!box || !session) return;
  const locked = !!session.signed;
  const open = locked ? [] : openRiskCues();
  const left = locked ? (session.risk_dismissals || []) : [...dismissed].map(([segment_id, reason]) => ({ segment_id, reason }));
  put(box,
    ...open.map((u) => el("div", { class: "gate-item" },
      el("span", {}, `✗ #${u.segment_id} 的風險線索（${u.category}）還沒有寫進紀錄：請補寫並引用該段，或註明不寫的理由。`),
      el("button", { type: "button", class: "ev", onclick: () => highlight([u.segment_id]) }, `看 #${u.segment_id}`),
      el("button", { type: "button", class: "confirm", onclick: () => dismissCue(u) }, "不納入紀錄（填理由）"))),
    ...left.map((d) => el("div", { class: "gate-item done" }, `#${d.segment_id} 未納入紀錄，理由：${d.reason}`)),
  );
}

function shorten(text, n = 60) {
  return text.length > n ? `${text.slice(0, n)}…` : text;
}

function flagLine(f) {
  return el("div", { class: "flag" },
    el("button", { type: "button", class: "ev", onclick: () => highlight([f.segment_id]) }, `#${f.segment_id}`),
    el("span", { title: f.quote }, `「${shorten(f.quote)}」`),
    f.negated ? el("span", { class: "flag-tag" }, "含否定語，請確認") : null,
    // Only a question with 你 from an unconfirmed speaker is likely the therapist asking.
    f.maybe_therapist ? el("span", { class: "flag-tag" }, "說話者未確認，可能是心理師的提問")
      : f.speaker_unconfirmed ? el("span", { class: "flag-tag" }, "說話者由模型推測，請對照錄音") : null,
    f.note ? el("div", { class: "flag-note" }, f.note) : null);
}

// A long session can raise dozens of cues. They are grouped by category, the
// most serious first, each showing a few lines, so the note stays on screen.
function riskGroups(flags) {
  const groups = new Map();
  for (const f of flags) {
    if (!groups.has(f.category)) groups.set(f.category, []);
    groups.get(f.category).push(f);
  }
  const rank = (items) => Math.min(...items.map((f) => { const i = LEVEL_ORDER.indexOf(f.level); return i < 0 ? 9 : i; }));
  return [...groups].sort((a, b) => rank(a[1]) - rank(b[1])).map(([category, items]) => {
    const level = LEVEL_ORDER[rank(items)] || "review";
    const shown = items.slice(0, SHOWN_PER_GROUP), rest = items.slice(SHOWN_PER_GROUP);
    return el("details", { class: `flag-group lvl-${level}`, open: level === "critical" || level === "high" },
      el("summary", {}, el("b", {}, category), ` ×${items.length}`, LEVEL_SHORT[level] ? el("span", { class: "flag-tag" }, LEVEL_SHORT[level]) : null),
      shown.map(flagLine),
      rest.length ? el("details", { class: "flag-more" }, el("summary", {}, `顯示其餘 ${rest.length} 筆`), rest.map(flagLine)) : null);
  });
}

function segList(ids) {
  const shown = ids.slice(0, 3).map((i) => `#${i}`).join("、");
  return ids.length > 3 ? `${shown} 等 ${ids.length} 處` : shown;
}

function riskPanel(risk) {
  const unknown = risk.speakers_confirmed === false;
  return el("div", { class: `risk-panel lvl-${risk.level}` },
    el("h4", {}, `風險線索：${RISK_NAMES[risk.level] ?? risk.level}`, risk.flags.length ? `（共 ${risk.flags.length} 筆）` : ""),
    riskGroups(risk.flags),
    risk.protective.length ? el("details", { class: "flag-group" },
      el("summary", {}, el("b", {}, "保護因子"), ` ×${risk.protective.length}`),
      risk.protective.map((p) => el("div", { class: "flag" },
        el("button", { type: "button", class: "ev", onclick: () => highlight([p.segment_id]) }, `#${p.segment_id}`), `「${shorten(p.quote)}」`))) : null,
    risk.flags.length ? el("div", { class: "checks" },
      // With uploaded audio nobody is confirmed as the therapist, so "not asked" cannot be claimed.
      el("span", {}, risk.screening_asked.length ? `✓ 心理師有詢問自殺意念的用語（${segList(risk.screening_asked)}）`
        : unknown ? "— 說話者未確認，無法判斷心理師是否詢問過自殺意念（請自行核對）" : "✗ 未見心理師詢問自殺意念"),
      el("span", {}, risk.safety_actions.length ? `✓ 心理師有提到安全計畫或轉介的用語（${segList(risk.safety_actions)}）`
        : unknown ? "— 說話者未確認，無法判斷心理師是否談到安全計畫或轉介（請自行核對）" : "✗ 未見心理師談到安全計畫或轉介"),
    ) : null,
    risk.checklist.length ? el("div", { class: "checklist" },
      el("div", { class: "checklist-title" }, "自殺風險評估要素（依關鍵詞判斷是否談到，不代表評估品質）"),
      risk.checklist.map((c) => el("span", { class: c.covered.length ? "done" : "missing" },
        c.covered.length ? `✓ ${c.item}（${segList(c.covered)}）` : `○ ${c.item}：可考慮補問或補記`)),
    ) : null,
    el("div", { class: "disclaimer" }, "提示僅供參考，不取代心理師的臨床判斷；未標示不代表沒有風險。線索來自關鍵詞比對，詞表尚待心理師確認，間接的說法仍可能漏掉。通報義務線索只提醒依法評估，系統不會自動通報。上傳錄音的說話者由模型推測，只有逐字稿標示的心理師用語才計入詢問與安全措施。"),
  );
}

// ----- session page -----

function renderSession(r, focusSeg) {
  session = r;
  currentClient = r.client_id;
  markActive(r.client_id);
  confirmed.clear(); // confirmations belong to one note
  keepReasons.clear();
  dismissed.clear();
  edited = false;
  verifying = false;
  adoptNote(r.note);
  const locked = !!r.signed;
  setSimNote(r.simulated === false ? "real" : "simulated");
  const main = document.getElementById("main");
  const riskSegs = new Set(r.risk.flags.map((f) => f.segment_id));

  const transcript = el("section", { class: "card transcript", "aria-label": "逐字稿" },
    el("h3", {}, "逐字稿 ", el("small", { lang: "en" }, "Transcript")),
    el("div", { class: "transcript-lines", tabindex: "0" },
      r.transcript.map((s) => el("div", { class: `seg${riskSegs.has(s.id) ? " risk" : ""}`, id: `seg-${s.id}` },
        el("span", { class: "t" }, `#${s.id} ${fmtTime(s.start)}`),
        el("span", { class: `who ${s.speaker}`, title: s.speaker_source === "model" ? "由本機模型依內容推測，請對照錄音確認" : "" }, speakerName(s)),
        el("span", { class: "said" }, riskSegs.has(s.id) ? el("span", { class: "risk-tag" }, "風險線索") : null, s.text),
      ))),
  );

  const notePanel = el("section", { class: `card note-card${locked ? " locked" : ""}`, "aria-label": "會談紀錄" },
    locked
      ? el("h3", {}, `已簽核紀錄（${r.note.template}）`, el("small", {}, "唯讀；更正請另寫補充說明"))
      : el("h3", {}, `紀錄草稿（${r.note.template}）`, el("small", {}, "AI 起草，逐句查核，由心理師修改後簽核")),
    el("div", { class: "counter", id: "verify-counter", role: "status", "aria-live": "polite" }),
    el("div", { class: "legend", "aria-label": "標示說明" },
      ["supported", "weak", "unsupported", "dirty", "confirmed"].map((k) =>
        el("span", { class: `key ${k}` }, el("span", { "aria-hidden": "true" }, STATES[k].mark), ` ${STATES[k].name}`))),
    riskPanel(r.risk),
    el("div", { id: "risk-gate" }),
    el("div", { id: "note-box" }),
    el("div", { class: "verify-bar" },
      el("span", { id: "verify-summary", role: "status", "aria-live": "polite" }),
      locked ? null : el("div", { class: "actions" },
        el("button", { type: "button", id: "next-btn", hidden: true, onclick: () => focusNextBlocking() }, "跳到下一句待處理"),
        el("button", { type: "button", onclick: addTestSentence, title: "加入一句逐字稿中沒有的內容，示範查核會把它攔下" }, "示範：插入捏造句"),
        el("button", { type: "button", id: "verify-btn", onclick: () => reverify() }, "重新驗證"),
        el("button", { type: "button", class: "primary", id: "sign-btn", onclick: sign }, "核對完成，簽核"),
      ),
    ),
    el("div", { id: "sign-status", role: "status", "aria-live": "polite" }),
    locked ? signedBox(r) : null,
  );

  const differs = serverStatus && !locked && r.engine !== serverStatus.engine;
  const head = el("div", { class: "session-head" },
    el("div", {},
      el("button", { type: "button", class: "back", onclick: () => { if (leaveOk()) openClient(r.client_id); } }, "← 回個案"),
      el("h2", { tabindex: "-1", id: "session-title" },
        `${r.client_alias || r.client_id}・第 ${r.session_no} 次會談・${r.date}`,
        el("span", { class: `sim-badge${r.simulated === false ? " real" : ""}` }, r.simulated === false ? "真實個案資料" : "模擬會談")),
      el("div", { class: "engine-line" },
        `${r.session_id}・這份${locked ? "紀錄的草稿" : "草稿"}由${engineName(r.engine)}產生`,
        differs ? `（先前產生的；目前設定的引擎是${engineName(serverStatus.engine)}）` : "",
        differs ? el("button", { type: "button", class: "confirm", onclick: (e) => regenerate(e.currentTarget) }, "用目前的引擎重新產生") : null),
    ),
    el("div", { class: "timings", title: "各步驟花的時間。「載入逐字稿」是讀取已存的逐字稿，不是語音轉寫的時間。" },
      Object.entries(r.timings_ms || {}).map(([k, v]) => el("span", {}, `${AGENT_NAMES[k] || k} ${v >= 1000 ? `${(v / 1000).toFixed(1)} 秒` : `${v} 毫秒`}`))),
  );

  // How the draft was made, when it matters: the model did not answer and the rule engine wrote it.
  const warnings = (r.warnings || []).length && !locked
    ? el("div", { class: "warnings", id: "warnings", role: "alert" }, r.warnings.map((w) => el("div", { "data-quote": demoQuote(w) }, w))) : null;
  main.replaceChildren(head, warnings || "", el("div", { class: "workspace" }, transcript, notePanel));
  renderRiskGate();
  renderNote();
  if (focusSeg) highlight([focusSeg]);
  head.querySelector("h2").focus({ preventScroll: true });
}

async function regenerate(btn) {
  if (!confirm("重新產生會丟掉這份草稿和您在這一頁做的修改。確定要重新產生？")) return;
  const my = nav, sid = session.session_id, template = session.note.template;
  await busy(btn, "重新產生中", async () => {
    try {
      const r = await post(`/api/sessions/${encodeURIComponent(sid)}/process?template=${encodeURIComponent(template)}`);
      if (my !== nav) return;
      renderSession(r);
    } catch (err) {
      if (my === nav) showMessage(`沒有重新產生：${err.message}`, true);
    }
  });
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
    await busy(form.querySelector("button"), "新增中", async () => {
      try {
        const out = await post(`/api/sessions/${encodeURIComponent(r.session_id)}/addendum`, { text: form.text.value, author: form.author.value });
        draw(out.addenda);
        form.text.value = "";
        showMessage("已新增補充說明。");
      } catch (err) {
        showMessage(`無法新增補充說明：${err.message}`, true);
      }
    });
  });
  return el("div", { class: "signed-box" },
    el("div", { class: "signed" }, `✓ 已由 ${sig.signed_by} 於 ${fmtDateTime(sig.signed_at)} 簽核`),
    sig.note_sha256 ? el("div", { class: "hashes", title: "簽核時由伺服器計算，用來比對紀錄與逐字稿之後有沒有被改動；不是電子簽章" },
      `紀錄雜湊 ${sig.note_sha256.slice(0, 16)}…・逐字稿雜湊 ${sig.transcript_sha256.slice(0, 16)}…・查核規則版本 ${sig.verifier_version}`) : null,
    list, form);
}

// ----- verifying and signing -----

function scheduleVerify() {
  clearTimeout(verifyTimer);
  verifyTimer = setTimeout(() => reverify(), 200);
}

async function reverify() {
  if (!session || session.signed) return false;
  if (verifying) { verifyAgain = true; return false; }
  clearTimeout(verifyTimer);
  const my = nav, sid = session.session_id;
  syncFromDom();
  const sent = notePayload();
  verifying = true;
  verifyAgain = false;
  const btn = document.getElementById("verify-btn");
  if (btn) { btn.disabled = true; btn.setAttribute("aria-busy", "true"); }
  renderSummary();
  let r = null, error = null;
  try {
    r = await post(`/api/sessions/${encodeURIComponent(sid)}/verify`, sent.payload);
  } catch (err) {
    error = err;
  }
  // The answer belongs to the session it was asked for. If the therapist has
  // opened another one, it must not be drawn there (and then signed there).
  if (my !== nav || !session || session.session_id !== sid) return false;
  verifying = false;
  if (btn && btn.isConnected) { btn.disabled = false; btn.removeAttribute("aria-busy"); }
  if (error) {
    renderSummary();
    showMessage(`無法重新驗證：${error.message}`, true);
    if (error.status === 409) openSession(sid); // signed elsewhere: show the record
    return false;
  }
  syncFromDom();
  for (const [key, keys] of Object.entries(sent.keys)) {
    const answer = (r.note.sections[key] || []);
    keys.forEach((k, i) => {
      const s = (sentences[key] || []).find((x) => x.key === k);
      const v = answer[i];
      if (!s || !v || s.text.trim() !== sent.texts.get(k)) return; // deleted or typed in since: stays "已修改"
      Object.assign(s, { status: v.status, support: v.support, reason: v.reason, must_confirm: v.must_confirm,
        model_rejected: v.model_rejected, source: v.source, evidence: v.evidence, verifiedText: v.text });
      if (document.activeElement && document.activeElement.closest && document.activeElement.closest(`.sentence[data-key="${k}"]`)) return;
      s.text = v.text;
    });
  }
  session.verification = r.verification;
  session.risk_uncovered = r.risk_uncovered;
  showMessage("");
  renderRiskGate();
  renderNote();
  if (verifyAgain) scheduleVerify();
  return true;
}

let signing = false;

async function sign() {
  if (signing || !session || session.signed) return;
  const btn = document.getElementById("sign-btn");
  // The server checks the note again whatever is sent; verifying first shows the
  // therapist the same result before a name is asked for.
  syncFromDom();
  if (counts().dirty && !(await reverify())) return;
  if (signBlocked()) {
    showMessage("紀錄還不能簽核：請先處理標示的句子，以及還沒寫進紀錄的風險線索。", true);
    return;
  }
  const dlg = document.getElementById("sign-dialog");
  const form = document.getElementById("sign-form");
  const c = counts();
  const kept = allSentences().filter((s) => confirmed.has(s.key) && (s.status === "weak" || s.status === "unsupported"));
  document.getElementById("sign-summary").textContent =
    `${session.client_alias || session.client_id}・第 ${session.session_no} 次會談（${session.date}）。這份紀錄共 ${c.total} 句，其中 ${kept.length} 句是查核標示後由您確認保留的；${dismissed.size} 則風險線索未納入紀錄。`;
  put(document.getElementById("sign-kept"),
    kept.length ? el("div", { class: "kept-title" }, "您確認保留的標示句：") : null,
    kept.length ? el("ul", {}, kept.map((s) => el("li", {}, s.text.trim(), el("div", { class: "flag-note" }, `標示原因：${s.reason}`)))) : null,
    dismissed.size ? el("div", { class: "kept-title" }, "未納入紀錄的風險線索：") : null,
    dismissed.size ? el("ul", {}, [...dismissed].map(([seg, reason]) => el("li", {}, `#${seg}：${reason}`))) : null,
  );
  form.signed_by.value = session.therapist || "";
  form.checked.checked = false;
  document.getElementById("sign-error").textContent = "";
  document.getElementById("sign-cancel").onclick = () => dlg.close();
  form.onsubmit = async (e) => {
    e.preventDefault();
    if (signing) return; // a second click or Enter while the first request is running
    const by = form.signed_by.value.trim();
    if (!by || !form.checked.checked) return;
    signing = true;
    const my = nav, sid = session.session_id;
    const confirmBtn = document.getElementById("sign-confirm");
    try {
      await busy(confirmBtn, "簽核中", () => post(`/api/sessions/${encodeURIComponent(sid)}/sign`, {
        signed_by: by, note: notePayload().payload,
        risk_dismissals: [...dismissed].map(([segment_id, reason]) => ({ segment_id, reason })),
      }));
      dlg.close();
      edited = false;
      // Show what the server filed, read-only, rather than what this page had.
      if (my === nav) await openSession(sid);
    } catch (err) {
      if (err.status === 409 && err.data && /already signed/.test(err.data.error || "")) {
        dlg.close(); // signed a moment ago (a double submit, or another window): show the record, not an error
        edited = false;
        if (my === nav) await openSession(sid);
        return;
      }
      document.getElementById("sign-error").textContent = `沒有簽核：${err.message}`;
      if (err.data && err.data.risk_uncovered && my === nav) {
        session.risk_uncovered = err.data.risk_uncovered;
        dlg.close();
        showMessage(`沒有簽核：${err.message}`, true);
        renderRiskGate();
        renderSummary();
      }
    } finally {
      signing = false;
      if (btn && btn.isConnected) btn.disabled = signBlocked();
    }
  };
  dlg.showModal();
  form.signed_by.focus();
}

// ---------- start ----------

setStep(1);
loadStatus();
loadClients().then((clients) => {
  // ?session=C001-S04 opens a session directly (handy for demos and screenshots).
  const params = new URLSearchParams(location.search);
  const sid = params.get("session");
  if (sid && SESSION_ID.test(sid)) {
    currentClient = sid.split("-")[0];
    markActive(currentClient);
    openSession(sid);
  } else if (clients.length) {
    const wanted = params.get("client");
    openClient(clients.some((c) => c.id === wanted) ? wanted : clients[0].id);
  }
});
