// ===========================================================================
// Gemini RAG Chatbot - frontend
// Relative API URLs, so the page works on localhost, in Docker or on any domain.
// User/model text is only ever inserted via textContent or escaped markdown.
// ===========================================================================

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const KEYS = { settings: "rag.settings.v2", upload: "rag.upload.v1", user: "rag.userId", theme: "rag.theme" };
const MAX_HISTORY_TURNS = 10;

const storage = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); }
    catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ }
  },
};

// Anonymous per-browser workspace ID (see backend/security.py - not real auth).
const USER_ID = (() => {
  let id = storage.get(KEYS.user, null);
  if (!id) {
    id = (crypto.randomUUID ? crypto.randomUUID() : Date.now() + Math.random().toString(16).slice(2)).replace(/[^A-Za-z0-9_-]/g, "");
    storage.set(KEYS.user, id);
  }
  return id;
})();

async function api(path, opts = {}) {
  const isJson = opts.body && !(opts.body instanceof FormData);
  const res = await fetch(path, {
    ...opts,
    headers: { "X-User-Id": USER_ID, ...(isJson ? { "Content-Type": "application/json" } : {}), ...(opts.headers || {}) },
  });
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    const d = data && data.detail;
    if (typeof d === "string") msg = d;
    else if (Array.isArray(d)) msg = d.map((e) => `${(e.loc || []).filter((x) => x !== "body").join(".")}: ${e.msg}`).join("\n");
    if (res.status === 429) msg += ` Try again in ${res.headers.get("Retry-After") || "a few"}s.`;
    throw new Error(msg);
  }
  return data;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null) node.append(c);
  return node;
}

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 2600);
}

// -------------------------------------------------------------- theme ---

function applyTheme(choice) {
  if (choice === "light" || choice === "dark") document.documentElement.dataset.theme = choice;
  else delete document.documentElement.dataset.theme;
  $$("[data-theme-choice]").forEach((b) => b.classList.toggle("active", b.dataset.themeChoice === (choice || "system")));
  storage.set(KEYS.theme, choice || "system");
}

// ----------------------------------------------------------- settings ---
// Any element with data-setting="name" (in the composer or the drawer) is a setting.

const DEFAULT_SETTINGS = {
  model: "", system_instruction: "", temperature: "", top_p: "", top_k: "",
  max_output_tokens: "", retrieval_top_k: "", metadata_filter: "",
  include_shared: true, include_mine: true, use_history: true,
};

function readSettings() {
  const out = { ...DEFAULT_SETTINGS };
  for (const input of $$("[data-setting]")) {
    const key = input.dataset.setting;
    if (input.type === "checkbox") out[key] = input.checked;
    else if (input.type === "range") out[key] = input.dataset.unset === "1" ? "" : input.value;
    else out[key] = input.value.trim();
  }
  return out;
}

function writeSettings(values) {
  const v = { ...DEFAULT_SETTINGS, ...values };
  for (const input of $$("[data-setting]")) {
    const key = input.dataset.setting;
    if (input.type === "checkbox") input.checked = !!v[key];
    else if (input.type === "range") {
      input.dataset.unset = v[key] === "" ? "1" : "0";
      input.value = v[key] === "" ? 1 : v[key];
    } else input.value = v[key] ?? "";
  }
  syncRangeOutputs();
}

function syncRangeOutputs() {
  for (const out of $$("output[data-for]")) {
    const input = $(`[data-setting="${out.dataset.for}"]`);
    out.textContent = input.dataset.unset === "1" ? "auto" : Number(input.value).toFixed(1);
  }
}

function saveSettings() { storage.set(KEYS.settings, readSettings()); }

// ------------------------------------------------------ markdown (safe) ---
// Escape first, then add a small set of tags: the output can't contain
// any HTML that came from the model.

const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function inline(s) {
  return s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
}

function renderMarkdown(text) {
  const lines = escapeHtml(text).split("\n");
  const html = [];
  let list = null; // "ul" | "ol"
  let para = [];
  let code = null;

  const flushPara = () => { if (para.length) { html.push(`<p>${inline(para.join(" "))}</p>`); para = []; } };
  const closeList = () => { if (list) { html.push(`</${list}>`); list = null; } };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (code !== null) {
      if (/^```/.test(line.trim())) { html.push(`<pre><code>${code.join("\n")}</code></pre>`); code = null; }
      else code.push(raw);
      continue;
    }
    if (/^```/.test(line.trim())) { flushPara(); closeList(); code = []; continue; }

    const h = line.match(/^(#{1,6})\s+(.*)$/);
    const ul = line.match(/^\s*[-*•]\s+(.*)$/);
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);

    if (h) { flushPara(); closeList(); html.push(`<${h[1].length <= 2 ? "h3" : "h4"}>${inline(h[2])}</${h[1].length <= 2 ? "h3" : "h4"}>`); }
    else if (ul || ol) {
      flushPara();
      const kind = ul ? "ul" : "ol";
      if (list !== kind) { closeList(); html.push(`<${kind}>`); list = kind; }
      html.push(`<li>${inline((ul || ol)[1])}</li>`);
    } else if (!line.trim()) { flushPara(); closeList(); }
    else { closeList(); para.push(line.trim()); }
  }
  if (code !== null) html.push(`<pre><code>${code.join("\n")}</code></pre>`);
  flushPara(); closeList();
  return html.join("");
}

// --------------------------------------------------------------- chat ---

const history = [];
let busy = false;

function placeComposer() {
  const form = $("#chat-form");
  const empty = $("#thread").children.length === 0;
  $("#hero").hidden = !empty;
  $("#thread").hidden = empty;
  (empty ? $("#hero-composer-slot") : $("#dock")).append(form);
  $("#user-input").placeholder = empty ? "Ask anything..." : "Ask a follow-up...";
}

function autosize() {
  const t = $("#user-input");
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 200) + "px";
}

const ICON_SOURCES = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
const ICON_ANSWER = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M12 3l2.2 5.6L20 9.5l-4.4 3.8L17 19l-5-3-5 3 1.4-5.7L4 9.5l5.8-.9z" fill="currentColor"/></svg>';

function sectionLabel(icon, text) {
  const label = el("div", { class: "section-label" });
  label.innerHTML = icon; // static SVG constant
  label.append(text);
  return label;
}

function renderSources(citations) {
  const grid = el("div", { class: "sources" });
  let openDetail = null;
  citations.forEach((c, i) => {
    const tagText = c.source === "shared" ? "Shared" : c.source === "mine" ? "My docs" : "Source";
    const card = el("button", { class: "source", type: "button", "aria-expanded": "false", title: `${c.title || "Untitled"} (click to show the passage)` },
      el("span", { class: "s-title", text: c.title || "Untitled" }),
      el("span", { class: "s-meta" },
        el("span", { class: "num", text: String(i + 1) }),
        el("span", { class: `tag ${c.source}`, text: tagText }),
        c.page ? el("span", { text: `p. ${c.page}` }) : null));
    card.addEventListener("click", () => {
      const wasOpen = card.getAttribute("aria-expanded") === "true";
      $$(".source", grid).forEach((s) => s.setAttribute("aria-expanded", "false"));
      if (openDetail) { openDetail.remove(); openDetail = null; }
      if (wasOpen) return;
      card.setAttribute("aria-expanded", "true");
      openDetail = el("div", { class: "source-detail", text: c.text || "(no passage text returned)" });
      grid.append(openDetail);
    });
    grid.append(card);
  });
  return grid;
}

function buildRequest(question) {
  const s = readSettings();
  const num = (v) => (v === "" ? null : Number(v));
  const int = (v) => (v === "" ? null : parseInt(v, 10));
  return {
    question,
    history: s.use_history ? history.slice(-MAX_HISTORY_TURNS * 2) : [],
    generation: {
      model: s.model || null,
      temperature: num(s.temperature),
      top_p: num(s.top_p),
      top_k: int(s.top_k),
      max_output_tokens: int(s.max_output_tokens),
      system_instruction: s.system_instruction || null,
    },
    retrieval: {
      top_k: int(s.retrieval_top_k),
      metadata_filter: s.metadata_filter || null,
      include_shared: s.include_shared,
      include_mine: s.include_mine,
    },
  };
}

async function ask(question, existingTurn = null) {
  if (busy || !question) return;
  busy = true;
  $("#send-btn").disabled = true;

  const turn = existingTurn || el("article", { class: "turn" }, el("h2", { class: "question", text: question }));
  const body = el("div", { class: "turn-body" },
    el("div", { class: "step" }, el("span", { class: "spinner" }), "Searching your knowledge base..."),
    el("div", { class: "skeleton" }, el("div", { class: "bar" }), el("div", { class: "bar" }), el("div", { class: "bar" })));
  $(".turn-body", turn)?.remove();
  turn.append(body);
  if (!existingTurn) $("#thread").append(turn);
  placeComposer();
  turn.scrollIntoView({ behavior: "smooth", block: "start" });

  try {
    const data = await api("/api/chat", { method: "POST", body: JSON.stringify(buildRequest(question)) });
    body.replaceChildren();
    if (data.citations.length) {
      body.append(sectionLabel(ICON_SOURCES, `Sources · ${data.citations.length}`), renderSources(data.citations));
    }
    const answer = el("div", { class: "answer" });
    answer.innerHTML = renderMarkdown(data.answer); // escaped before formatting
    body.append(sectionLabel(ICON_ANSWER, "Answer"), answer);

    const copyBtn = el("button", { class: "mini-btn", type: "button", text: "⧉ Copy" });
    copyBtn.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(data.answer); toast("Answer copied"); } catch { toast("Copy failed"); }
    });
    const retryBtn = el("button", { class: "mini-btn", type: "button", text: "↻ Rewrite" });
    retryBtn.addEventListener("click", () => ask(question, turn));
    body.append(el("div", { class: "answer-foot" },
      el("span", { class: "meta", text: `${data.model} · ${data.searched_stores} knowledge base${data.searched_stores === 1 ? "" : "s"} searched` }),
      copyBtn, retryBtn));

    if (!existingTurn) history.push({ role: "user", text: question }, { role: "model", text: data.answer.slice(0, 8000) });
  } catch (err) {
    const retryBtn = el("button", { class: "mini-btn", type: "button", text: "↻ Try again" });
    retryBtn.addEventListener("click", () => ask(question, turn));
    body.replaceChildren(el("div", { class: "error-box", text: err.message }), el("div", { class: "answer-foot" }, retryBtn));
  } finally {
    busy = false;
    $("#send-btn").disabled = false;
    $("#user-input").focus();
  }
}

function newThread() {
  history.length = 0;
  $("#thread").replaceChildren();
  placeComposer();
  closeAll();
  $("#user-input").focus();
}

// ---------------------------------------------------------- documents ---

function setUploadMsg(text, cls = "") {
  const line = $("#upload-msg");
  line.textContent = text;
  line.className = `status-line ${cls}`;
}

function parseMetadata(text) {
  return text.split("\n").map((l) => l.trim()).filter(Boolean).map((line) => {
    const i = line.indexOf("=");
    if (i < 1) throw new Error(`Metadata line "${line}" must look like key=value`);
    const key = line.slice(0, i).trim();
    const val = line.slice(i + 1).trim();
    if (val.includes("|")) return { key, value: val.split("|").map((x) => x.trim()).filter(Boolean) };
    if (val !== "" && !isNaN(Number(val))) return { key, value: Number(val) };
    return { key, value: val };
  });
}

function showChosenFile() {
  const f = $("#file-input").files[0];
  $("#dz-title").textContent = f ? `📄 ${f.name}` : "";
  if (!f) $("#dz-title").append("Drop a file here or ", el("u", { text: "browse" }));
  $("#dropzone").classList.toggle("has-file", !!f);
}

async function uploadFile(event) {
  event.preventDefault();
  const form = event.target;
  const file = $("#file-input").files[0];
  if (!file) { setUploadMsg("Choose a file first.", "error"); return; }

  let options;
  try {
    options = {
      display_name: form.elements.display_name.value.trim() || null,
      chunking: {
        max_tokens_per_chunk: parseInt(form.elements.max_tokens_per_chunk.value, 10),
        max_overlap_tokens: parseInt(form.elements.max_overlap_tokens.value, 10),
      },
      metadata: parseMetadata(form.elements.metadata.value),
    };
  } catch (err) { setUploadMsg(err.message, "error"); return; }
  storage.set(KEYS.upload, { ...options.chunking, metadata: form.elements.metadata.value });

  const fd = new FormData();
  fd.append("file", file);
  fd.append("options", JSON.stringify(options));

  $("#upload-btn").disabled = true;
  setUploadMsg(`Uploading ${file.name}...`, "busy");
  try {
    const job = await api("/api/uploads", { method: "POST", body: fd });
    setUploadMsg(`Indexing "${job.display_name}"... you can keep chatting.`, "busy");
    $("#file-input").value = "";
    form.elements.display_name.value = "";
    showChosenFile();
    loadJobs();
    pollJob(job.job_id);
  } catch (err) {
    setUploadMsg(err.message, "error");
  } finally {
    $("#upload-btn").disabled = false;
  }
}

const activePolls = new Set();
async function pollJob(jobId, attempt = 0) {
  if (attempt === 0) {
    if (activePolls.has(jobId)) return;
    activePolls.add(jobId);
  }
  try {
    const job = await api(`/api/uploads/${encodeURIComponent(jobId)}`);
    if (job.status === "processing") {
      // Back off (2s, 3s, 4.5s ... max 15s) to keep server load low with many users.
      setTimeout(() => pollJob(jobId, attempt + 1), Math.min(15000, 2000 * 1.5 ** attempt));
      return;
    }
    activePolls.delete(jobId);
    if (job.status === "active") { setUploadMsg(`"${job.display_name}" is ready to search.`, "ok"); toast(`✅ ${job.display_name} indexed`); }
    else setUploadMsg(`Indexing failed: ${job.error || "unknown error"}`, "error");
    loadJobs();
    loadDocuments();
  } catch (err) {
    activePolls.delete(jobId);
    setUploadMsg(err.message, "error");
  }
}

function docIcon(name = "") {
  const ext = (name.split(".").pop() || "").toLowerCase();
  const kind = ["pdf", "txt", "md"].includes(ext) ? ext : "other";
  return el("span", { class: `doc-icon ${kind}`, text: ext && ext.length <= 4 ? ext : "doc" });
}

function fmtBytes(n) {
  if (!n) return "";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
}

const emptyItem = (text) => el("li", { class: "empty", text });

async function loadDocuments() {
  const list = $("#doc-list");
  try {
    const docs = await api("/api/documents");
    const count = $("#doc-count");
    count.hidden = !docs.length;
    count.textContent = docs.length;
    if (!docs.length) { list.replaceChildren(emptyItem("No documents yet. Upload one above.")); return; }
    list.replaceChildren(...docs.map((d) => {
      const state = (d.state || "").replace("STATE_", "").toLowerCase();
      const meta = Object.entries(d.metadata || {}).map(([k, v]) => `${k}=${Array.isArray(v) ? v.join("|") : v}`).join(", ");
      const del = el("button", { class: "del", type: "button", text: "Delete" });
      del.addEventListener("click", () => deleteDocument(d, del));
      return el("li", {},
        docIcon(d.display_name || ""),
        el("div", { class: "doc-info" },
          el("div", { class: "name", text: d.display_name || d.name, title: d.display_name || d.name }),
          el("div", { class: "sub", text: [fmtBytes(d.size_bytes), meta].filter(Boolean).join(" · ") || " " })),
        state ? el("span", { class: `badge ${state}`, text: state }) : null,
        del);
    }));
  } catch (err) {
    list.replaceChildren(emptyItem(err.message));
  }
}

async function deleteDocument(doc, button) {
  // Two-click confirm (no blocking browser dialogs).
  if (!button.classList.contains("confirm")) {
    button.classList.add("confirm");
    button.textContent = "Confirm?";
    setTimeout(() => { button.classList.remove("confirm"); button.textContent = "Delete"; }, 3000);
    return;
  }
  button.disabled = true;
  try {
    await api(`/api/documents/${doc.name.split("/").map(encodeURIComponent).join("/")}`, { method: "DELETE" });
    toast("Document deleted");
    loadDocuments();
  } catch (err) {
    setUploadMsg(err.message, "error");
    button.disabled = false;
  }
}

async function loadJobs() {
  const list = $("#job-list");
  try {
    const jobs = await api("/api/uploads");
    if (!jobs.length) { list.replaceChildren(emptyItem("No uploads yet.")); return; }
    list.replaceChildren(...jobs.slice(0, 8).map((j) => el("li", {},
      docIcon(j.filename),
      el("div", { class: "doc-info" },
        el("div", { class: "name", text: j.display_name, title: j.display_name }),
        el("div", { class: "sub", text: j.error || `chunk ${j.max_tokens_per_chunk} · overlap ${j.max_overlap_tokens}`, title: j.error || "" })),
      el("span", { class: `badge ${j.status}`, text: j.status === "processing" ? "indexing" : j.status }))));
    jobs.filter((j) => j.status === "processing").forEach((j) => pollJob(j.job_id));
  } catch (err) {
    list.replaceChildren(emptyItem(err.message));
  }
}

// ------------------------------------------------------------ drawers ---

function closeAll() {
  $$(".drawer").forEach((d) => (d.hidden = true));
  $("#sidebar").classList.remove("open");
  $("#scrim").hidden = true;
  $$(".nav-link").forEach((b) => b.classList.toggle("active", b.id === "nav-home"));
}

function openDrawer(id) {
  const wasOpen = !$(`#${id}`).hidden;
  closeAll();
  if (wasOpen) return;
  $(`#${id}`).hidden = false;
  $("#scrim").hidden = false;
  $$(".nav-link").forEach((b) => b.classList.toggle("active", b.dataset.panel === id));
  if (id === "docs-panel") { loadDocuments(); loadJobs(); }
  $(`#${id} .close`).focus();
}

// -------------------------------------------------------------- setup ---

async function loadOptions() {
  try {
    const o = await api("/api/options");
    $("#model-select").replaceChildren(
      el("option", { value: "", text: `Auto · ${o.default_model}` }),
      ...o.models.map((m) => el("option", { value: m, text: m })));
    writeSettings(storage.get(KEYS.settings, {}));

    const c = o.chunking;
    const saved = storage.get(KEYS.upload, {});
    Object.assign($("#chunk-size"), { min: c.max_tokens_per_chunk.min, max: c.max_tokens_per_chunk.max, value: saved.max_tokens_per_chunk ?? c.max_tokens_per_chunk.default });
    Object.assign($("#chunk-overlap"), { min: c.max_overlap_tokens.min, max: c.max_overlap_tokens.max, value: saved.max_overlap_tokens ?? c.max_overlap_tokens.default });
    $("#chunk-range").textContent = `${c.max_tokens_per_chunk.min}–${c.max_tokens_per_chunk.max}`;
    $("#overlap-range").textContent = `${c.max_overlap_tokens.min}–${c.max_overlap_tokens.max}`;
    if (saved.metadata) $("#upload-form").elements.metadata.value = saved.metadata;

    const l = o.limits;
    $("#file-input").accept = l.allowed_extensions.join(",");
    $("#upload-limits").textContent = `PDF, TXT, DOCX, MD and more · up to ${l.max_upload_mb} MB · max ${l.max_documents_per_user} files`;
    if (!o.shared_store_available) {
      $("[data-setting='include_shared']").closest("label").title = "No shared knowledge base has been loaded on this server yet.";
    }
  } catch (err) {
    toast(`Could not load server options: ${err.message}`);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  applyTheme(storage.get(KEYS.theme, "system"));
  $("#user-id").textContent = USER_ID;
  writeSettings(storage.get(KEYS.settings, {}));
  placeComposer();

  // Composer
  const input = $("#user-input");
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#chat-form").requestSubmit(); }
  });
  $("#chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q || busy) return;
    input.value = "";
    autosize();
    ask(q);
  });
  $$("#suggestions .chip").forEach((chip) => chip.addEventListener("click", () => ask(chip.textContent.replace(/^\S+\s/, ""))));

  // Settings: auto-save; range sliders start in "auto" until moved.
  document.addEventListener("input", (e) => {
    if (!e.target.matches("[data-setting]")) return;
    if (e.target.type === "range") e.target.dataset.unset = "0";
    syncRangeOutputs();
    saveSettings();
  });
  document.addEventListener("change", (e) => { if (e.target.matches("[data-setting]")) saveSettings(); });
  $("#reset-settings").addEventListener("click", () => { writeSettings(DEFAULT_SETTINGS); saveSettings(); toast("Settings reset"); });

  // Navigation
  $("#new-chat").addEventListener("click", newThread);
  $("#new-chat-mobile").addEventListener("click", newThread);
  $("#nav-home").addEventListener("click", closeAll);
  $$("[data-panel]").forEach((b) => b.addEventListener("click", () => openDrawer(b.dataset.panel)));
  $$(".drawer .close").forEach((b) => b.addEventListener("click", closeAll));
  $("#scrim").addEventListener("click", closeAll);
  $("#menu-btn").addEventListener("click", () => { $("#sidebar").classList.add("open"); $("#scrim").hidden = false; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAll(); });
  $$("[data-theme-choice]").forEach((b) => b.addEventListener("click", () => applyTheme(b.dataset.themeChoice)));

  // Upload: click or drag & drop
  const dz = $("#dropzone");
  $("#file-input").addEventListener("change", showChosenFile);
  ["dragenter", "dragover"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", (e) => {
    if (!e.dataTransfer.files.length) return;
    $("#file-input").files = e.dataTransfer.files;
    showChosenFile();
  });
  $("#upload-form").addEventListener("submit", uploadFile);
  $("#refresh-docs").addEventListener("click", loadDocuments);

  loadOptions();
  loadDocuments(); // fills the sidebar document count
  input.focus();
});
