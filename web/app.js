"use strict";

// Haven therapist UI. Talks only to the local Haven server (same origin).

const SECTION_NAMES = {
  S: "S 主觀資料", O: "O 客觀資料", A: "A 評估", P: "P 計畫", D: "D 資料",
};
const RISK_NAMES = { none: "未偵測到風險線索", review: "需要留意", high: "高度關注", critical: "立即評估" };
const STATUS_NAMES = { supported: "有逐字稿支持", weak: "支持不足", unsupported: "無支持證據" };
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
  const res = await fetch(path, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
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
  const color = m.status === "deteriorated" ? "var(--bad)" : m.status === "not_on_track" ? "var(--warn)" : m.status === "improved" ? "var(--good)" : "var(--accent)";
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
      const r = await api(`/api/upload?client=${encodeURIComponent(id)}&session_id=${encodeURIComponent(upForm.session_id.value)}`, {
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
  const r = await api(`/api/sessions/${sid}`);
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
    sections[sec.dataset.key] = [...sec.querySelectorAll(".sentence")].map((s) => ({
      text: s.querySelector(".txt").textContent.trim(),
      evidence: JSON.parse(s.dataset.evidence),
    })).filter((s) => s.text);
  });
  return { template: currentSession.note.template, engine: currentSession.note.engine, sections };
}

function sentenceRow(s) {
  const row = el("div", { class: `sentence ${s.status}`, "data-evidence": JSON.stringify(s.evidence), title: STATUS_NAMES[s.status] || "" },
    el("span", { class: "txt", contenteditable: "true", onfocus: () => highlight(s.evidence) }, s.text),
    el("span", { class: "ev", onclick: () => highlight(s.evidence) }, s.evidence.length ? `#${s.evidence.join(", #")}` : "無來源"),
  );
  return row;
}

function renderNote(container, note, verification) {
  container.replaceChildren(
    ...Object.entries(note.sections).map(([key, items]) => el("div", { class: "note-section", "data-key": key },
      el("h4", {}, SECTION_NAMES[key] || key),
      items.length ? items.map(sentenceRow) : el("div", { class: "sentence", "data-evidence": "[]" }, el("span", { class: "txt", contenteditable: "true" }, "")),
    )),
  );
  const bar = document.getElementById("verify-summary");
  bar.textContent = `驗證 agent：${verification.supported}/${verification.total} 句有逐字稿支持` +
    (verification.weak ? `，${verification.weak} 句支持不足` : "") +
    (verification.unsupported ? `，${verification.unsupported} 句無支持證據（需修改或刪除才能簽核）` : "");
  document.getElementById("sign-btn").disabled = !verification.ready_to_sign || !!currentSession.signature;
}

function renderSession(r, focusSeg) {
  currentSession = r;
  const main = document.getElementById("main");
  const riskSegs = new Set(r.risk.flags.map((f) => f.segment_id));

  const transcript = el("section", { class: "card transcript" },
    el("h3", {}, "逐字稿 ", el("small", {}, "Transcript")),
    r.transcript.map((s) => el("div", { class: `seg${riskSegs.has(s.id) ? " risk" : ""}`, id: `seg-${s.id}` },
      el("span", { class: "t" }, `#${s.id} ${fmtTime(s.start)}`),
      el("span", { class: `who ${s.speaker}` }, s.speaker === "client" ? "個案" : s.speaker === "therapist" ? "心理師" : "說話者"),
      el("span", {}, s.text),
    )),
  );

  const risk = r.risk;
  const riskPanel = el("div", { class: `risk-panel lvl-${risk.level}` },
    el("h4", {}, `風險線索：${RISK_NAMES[risk.level]}`),
    risk.flags.map((f) => el("div", { class: "flag", onclick: () => highlight([f.segment_id]) },
      el("b", {}, `[${f.category}]`), `#${f.segment_id}「${f.quote}」`, f.negated ? "（含否定語，請確認）" : "")),
    risk.protective.length ? el("div", { class: "flag" }, el("b", {}, "[保護因子]"),
      risk.protective.map((p) => `#${p.segment_id}「${p.quote}」`).join(" ")) : null,
    risk.flags.length ? el("div", { class: "checks" },
      el("span", {}, risk.screening_asked.length ? `✓ 已詢問自殺意念（#${risk.screening_asked.join(", #")}）` : "✗ 逐字稿中未見自殺意念詢問"),
      el("span", {}, risk.safety_actions.length ? `✓ 已有安全措施（#${risk.safety_actions.join(", #")}）` : "✗ 未見安全計畫或轉介"),
    ) : null,
    el("div", { class: "disclaimer" }, "提示僅供參考，不取代心理師的臨床判斷；未標示不代表沒有風險。"),
  );

  const noteBox = el("div", {});
  const signBtn = el("button", { class: "primary", id: "sign-btn", onclick: sign }, "確認並簽核");
  const notePanel = el("section", { class: "card" },
    el("h3", {}, `紀錄草稿（${r.note.template}）`, el("small", {}, "Draft note — edit before signing")),
    riskPanel,
    noteBox,
    el("div", { class: "verify-bar" },
      el("span", { id: "verify-summary" }),
      el("div", { class: "actions" },
        el("button", { onclick: addTestSentence, title: "加入一句逐字稿中沒有的內容，示範驗證 agent 會抓出來" }, "加入測試句"),
        el("button", { onclick: reverify }, "重新驗證"),
        signBtn,
      ),
    ),
    el("div", { id: "sign-status" }, r.signature ? el("span", { class: "signed" }, `已由 ${r.signature.signed_by} 於 ${r.signature.signed_at} 簽核`) : null),
  );

  const head = el("div", { class: "session-head" },
    el("div", {},
      el("button", { class: "back", onclick: () => openClient(r.client_id) }, "← 回個案"),
      el("h2", {}, `${r.session_id}・第 ${r.session_no} 次會談・${r.date}`),
    ),
    el("div", { class: "timings" },
      Object.entries(r.timings_ms).map(([k, v]) => el("span", {}, `${AGENT_NAMES[k] || k} ${v} ms`)),
      el("span", {}, r.engine),
    ),
  );

  main.replaceChildren(head, el("div", { class: "workspace" }, transcript, notePanel));
  renderNote(noteBox, r.note, r.verification);
  if (focusSeg) highlight([focusSeg]);
  noteBox.dataset.ready = "1";
}

async function reverify() {
  const r = await api(`/api/sessions/${currentSession.session_id}/verify`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(collectNote()),
  });
  currentSession.note = r.note;
  currentSession.verification = r.verification;
  renderNote(document.querySelector(".note-section").parentElement, r.note, r.verification);
}

function addTestSentence() {
  const first = document.querySelector(".note-section");
  const row = sentenceRow({ text: "個案表示與母親關係良好，最近常一起出遊。", evidence: [], status: "unchecked" });
  first.append(row);
  reverify();
}

async function sign() {
  const by = prompt("簽核心理師姓名", "王心理師");
  if (!by) return;
  const r = await api(`/api/sessions/${currentSession.session_id}/sign`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ signed_by: by, note: collectNote() }),
  });
  currentSession.signature = r;
  document.getElementById("sign-status").replaceChildren(el("span", { class: "signed" }, `已由 ${r.signed_by} 於 ${r.signed_at} 簽核`));
  document.getElementById("sign-btn").disabled = true;
}

loadStatus();
loadClients().then(() => {
  const first = document.querySelector("#client-list li");
  if (first) openClient(first.dataset.id);
});
