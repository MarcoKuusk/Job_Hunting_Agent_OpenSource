"use strict";

// Friendly names + cost tags for each job source.
const SOURCE_META = {
  remoteok:       { label: "RemoteOK",         cost: "free" },
  arbeitnow:      { label: "Arbeitnow",        cost: "free" },
  remotive:       { label: "Remotive",         cost: "free" },
  weworkremotely: { label: "We Work Remotely", cost: "free" },
  linkedin:       { label: "LinkedIn",         cost: "paid" },
  upwork:         { label: "Upwork",           cost: "paid" },
};

// Turns a technical setup-status name into a plain-language problem + fix.
const SETUP_HELP = {
  "Claude API key":       { core: true,  msg: "Add your Anthropic API key in Settings.", tab: "settings" },
  "Google Sheet ID (optional)":    { core: false, msg: "Google Sheet sync is not connected." },
  "Google credentials (optional)": { core: false, msg: "Google Sheet sync is not connected." },
  "Profile":              { core: true,  msg: "Add a short summary and at least one target role.", tab: "settings" },
  "Search keywords":      { core: true,  msg: "Add at least one keyword so I know which jobs to keep.", tab: "settings" },
  "Résumé / CV":          { core: true,  msg: "Upload your CV in Settings.", tab: "settings" },
  "Apify token":          { core: true,  msg: "Add an Apify token or turn off LinkedIn and Upwork.", tab: "settings" },
  "Telegram":             { core: false, msg: "Add Telegram details if notifications are enabled." },
};

const PAGE_SIZE = 24;

let MATCH_ROWS = [];       // every locally saved job, plus optional Google updates
let VISIBLE_ROWS = [];     // MATCH_ROWS after the filter bar
let MIN_SCORE = 70;        // what counts as a great fit (from the server)
let SHOWN = PAGE_SIZE;     // how many cards are rendered right now
let SEARCH_POLL = null;
let LAST_TRIGGER = null;   // the card button that opened the drawer
let SELECTED_ROW = null;   // the job currently open in the drawer

let FILTERS = { fit: "great", q: "", source: "", sort: "score", hideApplied: false };

// ---------- helpers ----------
async function api(url, opts) {
  let res;
  try {
    res = await fetch(url, opts);
  } catch (e) {
    return { ok: false, error: "I couldn't reach the app (" + url + "): " + e.message +
      ". Is the black Job Finder window still open?" };
  }

  // Read the body as text and parse it ourselves, so that when something goes
  // wrong we can SHOW what actually came back instead of just saying it was
  // unexpected. Diagnosing this blind is what a local tool should never make
  // you do.
  let text = "";
  try { text = await res.text(); } catch (e) {
    return { ok: false, error: "The answer from " + url + " was cut off: " + e.message };
  }
  let data = null;
  try { data = JSON.parse(text); } catch (e) { /* not JSON, reported below */ }

  if (!data || typeof data !== "object") {
    const type = res.headers.get("content-type") || "no content-type";
    const peek = text.slice(0, 160).replace(/\s+/g, " ") || "(empty body)";
    return { ok: false, error:
      "Unexpected answer from " + url + " — status " + res.status + ", " + type +
      ", " + text.length + " bytes. It starts: " + peek };
  }
  if (!res.ok && !data.error) data.error = "Request failed (" + res.status + ").";
  return data;
}
function post(url, body) {
  return api(url, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}) });
}
const $ = (id) => document.getElementById(id);
const linesToVal = (list) => (list || []).join("\n");
function setMsg(el, text, kind) {
  el.textContent = text || "";
  el.className = "status-msg" + (kind ? " " + kind : "");
}
function goTab(name) {
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === name));
  window.scrollTo({ top: 0, behavior: "smooth" });
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;",
    ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
// localStorage throws in a private window and comes back empty after a clear,
// so nothing here may be load-bearing.
function readStore(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch (e) { return fallback; }
}
function writeStore(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* ignore */ }
}

// ---------- theme ----------
// Three states: follow the operating system (no stored value), forced light,
// forced dark. The inline script in <head> applies the stored one before paint.
const THEME_LABEL = { system: "🌗 Theme: auto", light: "☀️ Theme: light", dark: "🌙 Theme: dark" };

function currentTheme() {
  try { return localStorage.getItem("theme") || "system"; } catch (e) { return "system"; }
}
function paintThemeButton() {
  $("btnTheme").textContent = THEME_LABEL[currentTheme()] || THEME_LABEL.system;
}
function cycleTheme() {
  const next = { system: "light", light: "dark", dark: "system" }[currentTheme()] || "light";
  try {
    if (next === "system") localStorage.removeItem("theme");
    else localStorage.setItem("theme", next);
  } catch (e) { /* ignore */ }
  if (next === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = next;
  paintThemeButton();
}

// ---------- tabs ----------
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => goTab(btn.dataset.tab));
});

// ---------- setup banner ----------
async function loadHome() {
  const banner = $("readyBanner");
  const status = await api("/api/status");
  const items = status.items || [];

  const problems = [];
  items.forEach((it) => {
    if (it.ok) return;
    const help = SETUP_HELP[it.name] || { core: true, msg: it.name + ": " + (it.detail || "not set") };
    problems.push({ ...help, name: it.name });
  });
  const coreProblems = problems.filter((p) => p.core);

  // When everything is fine, say nothing at all — a green bar on every visit
  // is just noise on a dashboard the user opens daily.
  if (coreProblems.length === 0) { banner.hidden = true; $("btnRunSearch").disabled = false; return; }

  banner.hidden = false;
  $("btnRunSearch").disabled = true;
  banner.className = "banner notready";
  let html = "⚠️ Let's finish setting up before your first search:";
  html += "<ul>" + coreProblems.map((p) => "<li>" + escapeHtml(p.msg) + "</li>").join("") + "</ul>";
  if (coreProblems.some((p) => p.tab === "settings")) {
    html += '<button class="btn secondary banner-btn" id="btnFixProfile">Open Settings →</button>';
  }
  banner.innerHTML = html;
  const fix = $("btnFixProfile");
  if (fix) fix.addEventListener("click", () => goTab("settings"));
}

// ---------- setup details ----------
function renderStatusList(el, items) {
  el.innerHTML = "";
  items.forEach((it) => {
    const row = document.createElement("div");
    row.className = "status-row";
    row.innerHTML = `<span class="dot ${it.ok ? "ok" : "bad"}"></span>` +
      `<strong>${escapeHtml(it.name)}</strong> <span class="detail">${escapeHtml(it.detail || "")}</span>`;
    el.appendChild(row);
  });
}
async function loadStatusDetails() {
  const r = await api("/api/status");
  renderStatusList($("statusList"), r.items || []);
}
async function runCheck() {
  $("checkResult").textContent = "Testing your connections…";
  const r = await post("/api/check", {});
  renderStatusList($("checkResult"), r.results || []);
}
// ---------- connection setup ----------
function paintConnectionState(id, configured, savedText, optional) {
  const el = $(id);
  el.textContent = configured ? (savedText || "Saved ✓") : (optional ? "Optional — not set" : "Not set");
  el.className = "connection-state " + (configured ? "ok" : (optional ? "" : "bad"));
}

function paintGoogleShareHelp(configured) {
  const help = $("googleShareHelp");
  const email = configured.google_service_email || "";
  if (!email) { help.hidden = true; help.textContent = ""; return; }
  help.hidden = false;
  help.innerHTML = "Now share your Google Sheet as <strong>Editor</strong> with: <code>" +
    escapeHtml(email) + "</code>";
}

async function loadConnections() {
  const result = await api("/api/connections");
  const configured = result.configured || {};
  paintConnectionState("anthropicState", configured.anthropic_key);
  paintConnectionState("googleSheetState", configured.google_sheet_id, "Saved ✓", true);
  paintConnectionState("googleCredentialsState", configured.google_credentials,
    configured.google_credentials_name ? "Uploaded: " + configured.google_credentials_name + " ✓" : "Uploaded ✓", true);
  paintConnectionState("apifyState", configured.apify_token, "Saved ✓", true);
  paintConnectionState("telegramTokenState", configured.telegram_token, "Saved ✓", true);
  paintConnectionState("telegramChatState", configured.telegram_chat_id, "Saved ✓", true);
  paintGoogleShareHelp(configured);
  $("btnOpenDashboard").hidden = !(configured.google_sheet_id && configured.google_credentials);
}

async function saveConnections() {
  const payload = {
    anthropic_key: $("anthropicKey").value,
    google_sheet_id: $("googleSheetId").value,
    apify_token: $("apifyToken").value,
    telegram_token: $("telegramToken").value,
    telegram_chat_id: $("telegramChatId").value,
  };
  setMsg($("connectionStatus"), "Saving…");
  const result = await post("/api/connections", payload);
  if (!result.ok) {
    setMsg($("connectionStatus"), result.error || "Could not save connection details.", "bad");
    return;
  }
  ["anthropicKey", "googleSheetId", "apifyToken", "telegramToken", "telegramChatId"]
    .forEach((id) => { $(id).value = ""; });
  setMsg($("connectionStatus"), "Saved locally ✓", "ok");
  await loadConnections();
  loadHome();
}

async function uploadGoogleCredentials(file) {
  if (!file) return;
  setMsg($("connectionStatus"), "Checking and saving the Google file…");
  const form = new FormData();
  form.append("credentials", file);
  let result = {};
  try {
    const response = await fetch("/api/upload-google-credentials", { method: "POST", body: form });
    result = await response.json();
  } catch (error) {
    result = { ok: false, error: "Could not upload the file: " + error.message };
  }
  $("googleCredentialsFile").value = "";
  if (!result.ok) {
    setMsg($("connectionStatus"), result.error || "Could not save the Google file.", "bad");
    return;
  }
  setMsg($("connectionStatus"), "Google file saved ✓", "ok");
  await loadConnections();
  loadHome();
}

// ---------- profile ----------
function pickyLabel(v) {
  v = Number(v);
  let word;
  if (v < 55) word = "Generous";
  else if (v < 70) word = "A good mix";
  else if (v < 80) word = "Balanced (recommended)";
  else if (v < 90) word = "Only strong matches";
  else word = "Only excellent matches";
  return word + " (" + v + ")";
}

async function loadProfile() {
  const p = await api("/api/profile");
  $("name").value = p.name || "";
  $("location").value = p.location || "";
  $("summary").value = p.summary || "";
  $("target_roles").value = linesToVal(p.target_roles);
  $("skills").value = linesToVal(p.skills);
  $("avoid").value = linesToVal(p.avoid);
  $("remote_only").checked = !!p.remote_only;
  $("min_salary").value = p.min_salary || "";
  $("locations_allowed").value = linesToVal(p.locations_allowed);
  $("keywords").value = linesToVal(p.keywords);
  $("search_terms").value = linesToVal(p.search_terms);

  const score = p.min_score != null ? p.min_score : 70;
  $("min_score").value = score;
  $("min_score_label").textContent = pickyLabel($("min_score").value);

  // current CV
  const cvEl = $("cvCurrent");
  if (p.cv_path) {
    cvEl.textContent = "Current CV: " + p.cv_path.split(/[\\/]/).pop();
    cvEl.classList.add("set");
  } else {
    cvEl.textContent = "No CV uploaded yet.";
    cvEl.classList.remove("set");
  }

  // source toggles
  const box = $("sourceToggles");
  box.innerHTML = "";
  const sources = p.sources || {};
  Object.keys(SOURCE_META).forEach((key) => {
    const meta = SOURCE_META[key];
    const label = document.createElement("label");
    label.className = "check";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.dataset.source = key;
    cb.checked = !!sources[key];
    label.appendChild(cb);
    label.appendChild(document.createTextNode(" " + meta.label));
    const tag = document.createElement("span");
    tag.className = "tag " + meta.cost;
    tag.textContent = meta.cost === "paid" ? "paid ~$0.23" : "free";
    label.appendChild(tag);
    box.appendChild(label);
  });
}

async function saveProfile() {
  const sources = {};
  document.querySelectorAll("#sourceToggles input").forEach((cb) => {
    sources[cb.dataset.source] = cb.checked;
  });
  const payload = {
    name: $("name").value, location: $("location").value, summary: $("summary").value,
    target_roles: $("target_roles").value, skills: $("skills").value, avoid: $("avoid").value,
    remote_only: $("remote_only").checked, min_salary: $("min_salary").value,
    locations_allowed: $("locations_allowed").value,
    keywords: $("keywords").value, search_terms: $("search_terms").value,
    min_score: $("min_score").value, sources: sources,
  };
  setMsg($("saveStatus"), "Saving…");
  const r = await post("/api/profile", payload);
  if (r.ok) {
    setMsg($("saveStatus"), "Saved ✓", "ok");
    loadHome();
    loadMatches();   // the fit threshold may have moved
  } else {
    setMsg($("saveStatus"), r.error || "Save failed", "bad");
  }
}

// ---------- CV upload ----------
async function uploadCv(file) {
  if (!file) return;
  setMsg($("cvStatus"), "Uploading " + file.name + "…");
  const form = new FormData();
  form.append("cv", file);
  const res = await fetch("/api/upload-cv", { method: "POST", body: form });
  let r = {};
  try { r = await res.json(); } catch (e) { /* ignore */ }
  if (r.ok) {
    setMsg($("cvStatus"), "Uploaded ✓", "ok");
    const cvEl = $("cvCurrent");
    cvEl.textContent = "Current CV: " + r.filename;
    cvEl.classList.add("set");
    loadHome();
  } else {
    setMsg($("cvStatus"), r.error || "Upload failed", "bad");
  }
}

// ---------- search ----------
async function runSearch() {
  const body = { dry_run: $("dry_run").checked, limit: $("limit").value || null };
  const r = await post("/api/search", body);
  if (!r.started) { setMsg($("searchState"), r.error || "Could not start", "bad"); return; }
  $("searchProgressCard").hidden = false;
  $("searchLog").textContent = "";
  $("searchSummary").innerHTML = "";
  $("searchActivity").textContent = "Starting the search…";
  $("searchProgress").classList.remove("done");
  $("btnRunSearch").disabled = true;
  setMsg($("searchState"), "");
  $("searchProgressCard").scrollIntoView({ behavior: "smooth", block: "nearest" });
  if (SEARCH_POLL) clearInterval(SEARCH_POLL);
  SEARCH_POLL = setInterval(pollSearch, 1500);
}

async function pollSearch() {
  const s = await api("/api/search/status");
  const log = s.log || [];
  $("searchLog").textContent = log.join("\n");
  const last = [...log].reverse().find((l) => l && l.trim());
  if (last) $("searchActivity").textContent = last;

  if (!s.running) {
    clearInterval(SEARCH_POLL); SEARCH_POLL = null;
    $("btnRunSearch").disabled = false;
    $("searchProgress").classList.add("done");
    if (s.error) {
      $("searchActivity").textContent = "Something went wrong.";
      $("searchSummary").innerHTML = `<p class="status-msg bad">${escapeHtml(s.error)}</p>`;
      return;
    }
    renderSearchSummary(s.result);
    loadMatches();
  }
}

function renderSearchSummary(r) {
  if (!r) return;
  const n = r.matches.length;
  const more = r.below_threshold || 0;
  $("searchActivity").textContent = "All done!";
  let html = `<p><span class="big-count">${n}</span> great ${n === 1 ? "fit" : "fits"} found`;
  if (more) html += `, plus ${more} more worth a look`;
  html += ".";
  if (r.dry_run) html += " This was a practice run, so nothing was saved.";
  else if (!r.scored_disabled) {
    html += ` ${r.saved} saved on this computer.`;
    if (r.logged) html += ` ${r.logged} synced to Google Sheets.`;
  }
  html += ` <span class="detail">(Checked ${r.fetched} jobs, scored ${r.scored}.)</span></p>`;
  if (n + more > 0) html += `<p>Your jobs are listed below. 👇</p>`;
  if (r.errors && r.errors.length) {
    html += `<p class="status-msg bad">Some sources had trouble: ${escapeHtml(r.errors.join("; "))}</p>`;
  }
  $("searchSummary").innerHTML = html;
}

// ---------- matches ----------
async function loadMatches() {
  $("jobGrid").innerHTML = "<p class='empty'>Loading…</p>";
  const r = await api("/api/matches");
  if (!r.ok) {
    $("jobGrid").innerHTML = `<p class="status-msg bad">${escapeHtml(
      r.error || "I couldn't read your saved jobs.")}</p>`;
    return;
  }
  MATCH_ROWS = r.rows || [];
  setMsg($("searchState"), r.warning || "", r.warning ? "bad" : "");
  if (typeof r.min_score === "number") MIN_SCORE = r.min_score;
  renderStats(r.counts || {});
  buildSourceOptions();
  applyFilters();
}

function renderStats(counts) {
  const strip = $("statStrip");
  if (!MATCH_ROWS.length) { strip.hidden = true; return; }
  strip.hidden = false;
  const today = new Date().toISOString().slice(0, 10);
  $("statGreat").textContent = counts.great || 0;
  $("statTotal").textContent = counts.total || MATCH_ROWS.length;
  $("statApplied").textContent = counts.applied || 0;
  $("statNew").textContent = MATCH_ROWS.filter((r) => r["Date found"] === today).length;
}

// Fit bands. "Great" is the threshold from Settings; anything within 15 points
// below it is still worth showing before we call it a long shot.
function band(score) {
  if (score === null || score === undefined) return "long";
  if (score >= MIN_SCORE) return "great";
  if (score >= Math.max(MIN_SCORE - 15, 0)) return "worth";
  return "long";
}
const BAND_TEXT = { great: "Great fit", worth: "Worth a look", long: "Long shot" };
const BAND_RING = { great: "high", worth: "mid", long: "low" };

function isApplied(row) {
  return String(row.Status || "").toLowerCase().includes("applied");
}

function buildSourceOptions() {
  const sel = $("fSource");
  const present = [...new Set(MATCH_ROWS.map((r) => r.Source).filter(Boolean))].sort();
  const keep = FILTERS.source;
  sel.innerHTML = '<option value="">All job boards</option>' +
    present.map((s) => {
      const label = (SOURCE_META[s] || {}).label || s;
      return `<option value="${escapeHtml(s)}">${escapeHtml(label)}</option>`;
    }).join("");
  sel.value = present.includes(keep) ? keep : "";
  FILTERS.source = sel.value;
}

function applyFilters() {
  const q = FILTERS.q.trim().toLowerCase();
  VISIBLE_ROWS = MATCH_ROWS.filter((row) => {
    if (FILTERS.fit !== "all" && band(row.Score) !== FILTERS.fit) return false;
    if (FILTERS.source && row.Source !== FILTERS.source) return false;
    if (FILTERS.hideApplied && isApplied(row)) return false;
    if (q) {
      const hay = ((row.Title || "") + " " + (row.Company || "")).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  if (FILTERS.sort === "date") {
    VISIBLE_ROWS.sort((a, b) => String(b["Date found"] || "").localeCompare(String(a["Date found"] || "")));
  } else {
    VISIBLE_ROWS.sort((a, b) => {
      const as = a.Score, bs = b.Score;
      if (as === null && bs === null) return 0;
      if (as === null) return 1;
      if (bs === null) return -1;
      return bs - as;
    });
  }

  SHOWN = PAGE_SIZE;
  renderChips();
  renderJobCards();
  writeStore("jobFilters", FILTERS);
}

function renderChips() {
  const tally = { all: MATCH_ROWS.length, great: 0, worth: 0, long: 0 };
  MATCH_ROWS.forEach((r) => { tally[band(r.Score)] += 1; });
  const defs = [
    ["great", "Great fits"], ["worth", "Worth a look"],
    ["long", "Long shots"], ["all", "Everything"],
  ];
  $("fitChips").innerHTML = defs.map(([key, label]) =>
    `<button class="chip ${FILTERS.fit === key ? "active" : ""}" data-fit="${key}">` +
    `${label}<span class="n">${tally[key]}</span></button>`).join("");
  document.querySelectorAll("[data-fit]").forEach((btn) => {
    btn.addEventListener("click", () => { FILTERS.fit = btn.dataset.fit; applyFilters(); });
  });
}

function renderJobCards() {
  const grid = $("jobGrid");
  const btnMore = $("btnShowMore");

  if (!MATCH_ROWS.length) {
    grid.innerHTML = "<p class='empty'>No jobs yet. Press <strong>Find jobs now</strong> above to look for some.</p>";
    btnMore.hidden = true;
    return;
  }
  if (!VISIBLE_ROWS.length) {
    grid.innerHTML = "<p class='empty'>No jobs match these filters. " +
      '<button class="btn secondary" id="btnClearFilters">Clear filters</button></p>';
    btnMore.hidden = true;
    $("btnClearFilters").addEventListener("click", clearFilters);
    return;
  }

  const page = VISIBLE_ROWS.slice(0, SHOWN);
  grid.innerHTML = page.map((row, i) => {
    const b = band(row.Score);
    const applied = isApplied(row);
    const score = row.Score === null || row.Score === undefined ? "?" : row.Score;
    const pct = typeof row.Score === "number" ? Math.max(0, Math.min(100, row.Score)) : 0;
    const where = [row.Location, (SOURCE_META[row.Source] || {}).label || row.Source]
      .filter(Boolean).join(" · ");
    const reasons = String(row.Reasons || "");
    return `<article class="jobcard ${applied ? "is-applied" : ""}">
      <div class="top">
        <div class="ring ${BAND_RING[b]}" style="--pct:${pct}" aria-hidden="true"><span>${escapeHtml(score)}</span></div>
        <div class="fit">${BAND_TEXT[b]}<span class="where">${escapeHtml(where)}</span></div>
        ${applied ? '<span class="pill">Applied</span>' : ""}
      </div>
      <h4>${escapeHtml(row.Title || "Untitled role")}</h4>
      <p class="org">${escapeHtml(row.Company || "")}</p>
      ${reasons ? `<p class="why">${escapeHtml(reasons)}</p>
        <button class="more" data-more="${i}">Read more</button>` : ""}
      <div class="foot">
        <button class="btn apply-btn" data-apply="${i}">✍️ ${applied ? "Write it again" : "Write my application"}</button>
        ${row.URL ? `<a href="${encodeURI(row.URL)}" target="_blank" rel="noopener">View posting ↗</a>` : ""}
      </div>
    </article>`;
  }).join("");

  // Indexes are into VISIBLE_ROWS, which is what the page is rendered from —
  // indexing MATCH_ROWS here would open the wrong job whenever a filter is on.
  grid.querySelectorAll("[data-apply]").forEach((btn) => {
    btn.addEventListener("click", () => chooseJob(Number(btn.dataset.apply), btn));
  });
  grid.querySelectorAll("[data-more]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const why = btn.previousElementSibling;
      const open = why.classList.toggle("open");
      btn.textContent = open ? "Show less" : "Read more";
    });
  });

  const left = VISIBLE_ROWS.length - page.length;
  btnMore.hidden = left <= 0;
  btnMore.textContent = `Show ${Math.min(left, PAGE_SIZE)} more (${left} left)`;
}

function clearFilters() {
  FILTERS = { fit: "all", q: "", source: "", sort: FILTERS.sort, hideApplied: false };
  $("fSearch").value = "";
  $("fSource").value = "";
  $("fHideApplied").checked = false;
  applyFilters();
}

// ---------- apply drawer ----------
// Picking a job is the ONLY thing the user has to do: choosing one starts the
// writing straight away. This still only produces documents; nothing is ever
// sent or submitted on their behalf.
function chooseJob(i, trigger) {
  SELECTED_ROW = VISIBLE_ROWS[i];
  if (!SELECTED_ROW) return;
  LAST_TRIGGER = trigger || null;

  $("applyJobTitle").textContent = SELECTED_ROW.Title || "This job";
  $("applyJobOrg").textContent =
    [SELECTED_ROW.Company, SELECTED_ROW.Location].filter(Boolean).join(" · ");
  $("draftResults").hidden = true;
  setMsg($("applyState"), "");
  $("btnOpen").dataset.url = SELECTED_ROW.URL || "";
  $("btnApplied").dataset.url = SELECTED_ROW.URL || "";

  $("drawerBackdrop").hidden = false;
  $("applyDrawer").hidden = false;
  document.body.classList.add("drawer-open");
  $("applyDrawer").scrollTop = 0;
  $("btnCloseDrawer").focus();

  draftDocs(false);
}

function closeDrawer() {
  $("applyDrawer").hidden = true;
  $("drawerBackdrop").hidden = true;
  document.body.classList.remove("drawer-open");
  if (LAST_TRIGGER && document.body.contains(LAST_TRIGGER)) LAST_TRIGGER.focus();
  LAST_TRIGGER = null;
}

// Turns the short bullet briefing into readable HTML.
function notesToHtml(text) {
  const out = [];
  let inList = false;
  String(text || "").split(/\r?\n/).forEach((raw) => {
    const line = raw.trim();
    if (!line) return;
    if (/^[-*]\s+/.test(line)) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push("<li>" + escapeHtml(line.replace(/^[-*]\s+/, "")) + "</li>");
    } else {
      if (inList) { out.push("</ul>"); inList = false; }
      out.push("<p>" + escapeHtml(line.replace(/^#+\s*/, "")) + "</p>");
    }
  });
  if (inList) out.push("</ul>");
  return out.join("");
}

async function draftDocs(force) {
  if (!SELECTED_ROW) return;
  const row = SELECTED_ROW;
  const progress = $("draftProgress");
  progress.hidden = false;
  progress.classList.remove("done");
  setMsg($("draftState"), force
    ? "Writing them again… (about 20 to 40 seconds)"
    : "Writing your cover letter and tailoring your CV… (about 20 to 40 seconds)");
  $("btnRedraft").disabled = true;

  const r = await post("/api/draft", {
    title: row.Title, company: row.Company, url: row.URL,
    location: row.Location, source: row.Source, force: !!force,
  });

  // The user may have closed the drawer, or opened another job, while this ran.
  if (SELECTED_ROW !== row) return;

  $("btnRedraft").disabled = false;
  progress.classList.add("done");
  if (!r.ok) {
    setMsg($("draftState"), r.error || "Something went wrong writing your documents.", "bad");
    return;
  }

  // Jobs saved before the full advert was being kept can only be drafted from
  // the title and company, so say so rather than quietly writing something
  // vaguer than usual.
  const thin = r.used_description ? "" :
    " I only have the job title and company for this one, so keep an eye on how specific it sounds.";
  setMsg($("draftState"), (r.cached
    ? "Ready (already written for this job earlier)."
    : "Ready. Have a read through before you send anything.") + thin, "ok");
  $("draftResults").hidden = false;
  $("coverText").value = r.cover_letter || "";
  $("cvText").value = r.tailored_cv || "";
  $("cvNotes").innerHTML = notesToHtml(r.cv_notes);

  setDownload($("dlCover"), r.cover_file);
  setDownload($("dlCv"), r.cv_file);
  $("savedPaths").textContent = r.folder ? "Also saved on your computer in: " + r.folder : "";
}

function setDownload(link, filename) {
  if (!filename) { link.hidden = true; return; }
  link.hidden = false;
  link.href = "/api/download/" + encodeURIComponent(filename);
  link.setAttribute("download", filename);
}

async function openPage() {
  const url = $("btnOpen").dataset.url;
  if (!url) { setMsg($("applyState"), "This job has no link.", "bad"); return; }
  const r = await post("/api/open", { url });
  setMsg($("applyState"), r.ok ? "Opened in your browser — review and submit it yourself." : (r.error || "Failed"),
    r.ok ? "ok" : "bad");
}
async function markApplied() {
  const url = $("btnApplied").dataset.url;
  const r = await post("/api/mark-applied", { url });
  const good = r.ok && r.updated;
  setMsg($("applyState"), good ? "Marked as applied ✓" : (r.ok ? "Couldn't find that job in your saved jobs." : (r.error || "Failed")),
    good ? "ok" : "bad");
  if (good) loadMatches();
}

// ---------- dashboard ----------
async function openDashboard() {
  const r = await api("/api/dashboard");
  if (r.url) window.open(r.url, "_blank", "noopener");
}

// ---------- misc ----------
document.querySelectorAll(".copy").forEach((btn) => {
  btn.addEventListener("click", () => {
    const ta = $(btn.dataset.target);
    ta.select();
    navigator.clipboard.writeText(ta.value).then(() => {
      const old = btn.textContent; btn.textContent = "Copied!";
      setTimeout(() => (btn.textContent = old), 1200);
    });
  });
});

// ---------- wire up ----------
$("btnTheme").addEventListener("click", cycleTheme);
$("btnCheck").addEventListener("click", runCheck);
$("btnSaveConnections").addEventListener("click", saveConnections);
$("btnChooseGoogleCredentials").addEventListener("click", () => $("googleCredentialsFile").click());
$("googleCredentialsFile").addEventListener("change", (e) => uploadGoogleCredentials(e.target.files[0]));
$("btnChooseCv").addEventListener("click", () => $("cvFile").click());
$("cvFile").addEventListener("change", (e) => uploadCv(e.target.files[0]));
$("min_score").addEventListener("input", () => { $("min_score_label").textContent = pickyLabel($("min_score").value); });
$("btnSaveProfile").addEventListener("click", saveProfile);
$("btnRunSearch").addEventListener("click", runSearch);
$("btnLoadMatches").addEventListener("click", loadMatches);
$("btnRedraft").addEventListener("click", () => draftDocs(true));
$("btnOpenDashboard").addEventListener("click", openDashboard);
$("btnOpen").addEventListener("click", openPage);
$("btnApplied").addEventListener("click", markApplied);
$("btnCloseDrawer").addEventListener("click", closeDrawer);
$("drawerBackdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("applyDrawer").hidden) closeDrawer();
});

$("btnShowMore").addEventListener("click", () => { SHOWN += PAGE_SIZE; renderJobCards(); });
$("fSource").addEventListener("change", (e) => { FILTERS.source = e.target.value; applyFilters(); });
$("fSort").addEventListener("change", (e) => { FILTERS.sort = e.target.value; applyFilters(); });
$("fHideApplied").addEventListener("change", (e) => { FILTERS.hideApplied = e.target.checked; applyFilters(); });
let searchDebounce = null;
$("fSearch").addEventListener("input", (e) => {
  clearTimeout(searchDebounce);
  const value = e.target.value;
  searchDebounce = setTimeout(() => { FILTERS.q = value; applyFilters(); }, 150);
});

// Load setup details lazily the first time the section is opened.
let statusLoaded = false;
document.querySelector(".setup-details").addEventListener("toggle", (e) => {
  if (e.target.open && !statusLoaded) { statusLoaded = true; loadStatusDetails(); }
});

// ---------- init ----------
// The page and the server can fall out of step: this page is read from disk on
// every request, but the Python behind it is whatever was running when the app
// was started. If they don't match, say so plainly instead of letting the
// mismatch surface as strange errors further down.
async function checkServerIsCurrent() {
  const r = await api("/api/version");
  const features = r.features || [];
  if (features.includes("guided-setup")) return true;
  const banner = $("readyBanner");
  banner.hidden = false;
  $("btnRunSearch").disabled = true;
  banner.className = "banner notready";
  banner.innerHTML = "⚠️ This page is newer than the app that's running." +
    "<ul><li>Close <strong>every</strong> Job Finder window (the black ones).</li>" +
    "<li>Wait a couple of seconds, then start Job Finder again.</li>" +
    "<li>Come back here and press Ctrl+F5.</li></ul>";
  return false;
}

(async function init() {
  paintThemeButton();
  const saved = readStore("jobFilters", null);
  if (saved && typeof saved === "object") FILTERS = { ...FILTERS, ...saved };
  $("fSearch").value = FILTERS.q || "";
  $("fSort").value = FILTERS.sort || "score";
  $("fHideApplied").checked = !!FILTERS.hideApplied;

  if (!(await checkServerIsCurrent())) return;
  loadHome();
  loadConnections();
  loadProfile();
  loadMatches();
})();
