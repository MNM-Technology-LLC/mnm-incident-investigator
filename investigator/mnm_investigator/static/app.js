/* Apache-2.0. All application and model content is rendered as text. */
"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  dashboard: null, model: null, investigation: null, evidence: new Map(),
  history: [], busy: new Set(), polling: false, jobPolling: false,
  recoveryPolling: false, modelPolling: false, timelineSignature: "", diagnosisSignature: "",
};

const toolNames = {
  get_service_health: "Check service health", get_service_map: "Map observed dependencies",
  query_metrics: "Measure request behavior", search_logs: "Search application logs",
  get_trace: "Follow a distributed trace",
};

function text(id, value) { $(id).textContent = value; }
function element(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined && value !== null) node.textContent = String(value);
  return node;
}
function number(value, digits = 0) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits }) : "—";
}
function percentage(value) { return typeof value === "number" ? `${number(value * 100, 1)}%` : "—"; }
function time(value) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "Unknown time" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
function windowLabel(window) { return window?.start && window?.end ? `${time(window.start)}–${time(window.end)}` : "Awaiting observation window"; }
function badge(id, value, kind = "neutral") { text(id, value); $(id).className = `badge ${kind}`; }
function message(value, error = false) {
  text("notice", value); $("notice").className = `notice${error ? " notice-error" : ""}`; $("notice").hidden = !value;
}
async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal, headers: { Accept: "application/json", ...options.headers } });
    let result;
    try { result = await response.json(); } catch { throw new Error(`The server returned an unreadable response (${response.status}).`); }
    if (!response.ok) {
      const detail = result.detail ?? result.error;
      throw new Error(typeof detail === "string" ? detail : `Request failed (${response.status}). Please check the application stack.`);
    }
    return result;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("The request timed out. Check that the local application stack is running.");
    if (error instanceof TypeError) throw new Error("Cannot reach the local application stack. Check the connection and try again.");
    throw error;
  } finally { clearTimeout(timer); }
}
function post(path, body, control = false) {
  return api(path, { method: "POST", headers: { "Content-Type": "application/json", ...(control ? { "X-Demo-Control": "1" } : {}) }, body: JSON.stringify(body) });
}
function refreshButtons() {
  const controlsBusy = state.busy.size > 0;
  const traffic = state.dashboard?.traffic?.running;
  $("traffic-button").disabled = controlsBusy;
  $("traffic-button").replaceChildren(element("span", "", traffic ? "Ⅱ" : "▷"), document.createTextNode(traffic ? "Stop traffic" : "Start traffic"));
  $("fault-button").disabled = controlsBusy || state.dashboard?.controls?.fault_enabled === true;
  $("fault-button").replaceChildren(element("span", "", "ϟ"), document.createTextNode(state.dashboard?.controls?.fault_enabled === true ? "Fault active" : "Trigger fault"));
  $("reset-button").disabled = controlsBusy;
  const investigating = state.investigation?.status === "running" || state.busy.has("investigate") || state.busy.has("restore");
  $("investigate-button").disabled = investigating || state.model?.available === false;
  $("investigate-button").replaceChildren(document.createTextNode(investigating ? "Investigating" : "Investigate"), element("span", investigating ? "spinner" : "", investigating ? "" : "↗"));
  $("question").disabled = investigating;
}

function renderDashboard(data) {
  state.dashboard = data;
  const metrics = data.metrics?.["orders-service"] ?? {};
  const count = metrics.request_count;
  const hasSamples = typeof count === "number" && count > 0;
  const success = hasSamples && typeof metrics.error_rate === "number" ? 1 - metrics.error_rate : null;
  text("success-rate", percentage(success));
  text("success-description", hasSamples ? `${number(count - (metrics.error_count ?? 0))} of ${number(count)} completed orders` : "Waiting for completed requests");
  $("success-rail").style.width = success === null ? "0%" : `${Math.max(0, Math.min(100, success * 100))}%`;
  $("success-rate").closest(".metric-card").classList.toggle("incident", success !== null && success < 0.95);
  text("request-rate", hasSamples ? number(metrics.requests_per_second, 1) : "—");
  text("request-description", hasSamples ? `${number(count)} completed requests in this window` : "Measured at orders-service");
  text("latency", hasSamples ? number(metrics.p95_ms) : "—");
  text("latency-note", hasSamples ? `${number(metrics.p50_ms)} ms median response` : "No samples yet");
  text("timeout-count", hasSamples ? number(metrics.timeout_count) : "—");
  $("timeout-count").closest(".metric-card").classList.toggle("incident", (metrics.timeout_count ?? 0) > 0);
  text("timeout-description", hasSamples ? `${number(metrics.error_count)} failed requests in this window` : "Observed in orders-service");
  const seconds = metrics.window_seconds ?? (data.window?.start && data.window?.end ? Math.round((Date.parse(data.window.end) - Date.parse(data.window.start)) / 1000) : 30);
  text("observation-window", `${number(seconds)}-second observation window`);
  for (const [name, id] of [["orders-service", "orders-health"], ["inventory-service", "inventory-health"]]) {
    const service = (Array.isArray(data.services) ? data.services : []).find((item) => item.service === name);
    const status = service?.status;
    badge(id, status === "healthy" ? "Healthy" : status === "degraded" ? "Degraded" : "No data", status === "healthy" ? "" : status === "degraded" ? "warning" : "neutral");
    $(id).title = status === "no_data" || !status ? "No completed request observations in this window" : `Measured from completed requests · ${windowLabel(data.window)}`;
  }
  text("telemetry-status", data.telemetry_available ? "Observed request telemetry" : "Telemetry unavailable");
  const traffic = data.traffic ?? {};
  text("traffic-detail", traffic.running ? `${number(traffic.requests_sent)} sent · ${number(traffic.successes)} successful · ${number(traffic.failures)} failed` : (traffic.requests_sent > 0 ? `Traffic stopped · ${number(traffic.requests_sent)} requests sent` : "Send repeatable synthetic requests."));
  const fault = data.controls?.fault_enabled;
  const scenario = fault === true ? "Controlled fault active" : fault === null || fault === undefined ? "Fault state unknown" : traffic.running ? "Traffic running" : "Ready to begin";
  $("scenario-state").replaceChildren(element("span", "small-dot"), document.createTextNode(scenario));
  $("scenario-state").className = `scenario-state${fault === true ? " warning" : ""}`;
  text("last-updated", `Observed ${windowLabel(data.window)}`);
  if (hasSamples && typeof metrics.requests_per_second === "number") {
    state.history.push(metrics.requests_per_second); state.history = state.history.slice(-36);
    if (state.history.length > 1) {
      const maximum = Math.max(...state.history, 1);
      const points = state.history.map((value, index) => `${index ? "L" : "M"}${(index * 240 / (state.history.length - 1)).toFixed(1)},${(24 - (value / maximum) * 20).toFixed(1)}`).join(" ");
      $("activity-path").setAttribute("d", points);
      $("activity-chart").setAttribute("aria-label", `Recent measured request activity: ${state.history.map((value) => number(value, 1)).join(", ")} requests per second. Each sample summarizes an overlapping observation window.`);
    }
  } else {
    state.history = []; $("activity-path").setAttribute("d", "");
    $("activity-chart").setAttribute("aria-label", "No request activity samples in this observation window");
  }
  refreshButtons();
}

async function pollDashboard() {
  if (state.polling) return;
  state.polling = true;
  try { renderDashboard(await api("/api/dashboard")); }
  catch (error) {
    text("telemetry-status", "Application stack unavailable");
    text("last-updated", state.dashboard ? "Connection lost · displayed observations may be stale" : "Application stack unavailable");
    if (!state.dashboard) message(error.message, true);
  } finally { state.polling = false; }
}
async function pollModel() {
  if (state.modelPolling) return;
  state.modelPolling = true;
  try { state.model = await api("/api/model"); }
  catch (error) { state.model = { available: false, detail: error.message }; }
  finally { state.modelPolling = false; }
  const available = state.model.available === true;
  $("model-status").querySelector(".status-dot").className = `status-dot${available ? "" : " unavailable"}`;
  text("model-label", available ? (state.model.model || "Local model connected") : "Local model unavailable");
  text("model-detail", available ? "Live AI · inference stays local" : "Application controls still available");
  $("model-notice").hidden = available;
  text("model-notice-detail", `${state.model.detail || "Connect Ollama to run a live AI investigation."}${state.model.model ? ` Configured model: ${state.model.model}.` : ""} Telemetry and demo controls remain available.`);
  refreshButtons();
}
async function control(name, path, body, success) {
  if (state.busy.size) return;
  state.busy.add(name); refreshButtons(); message("");
  try {
    await post(path, body, true);
    message(success);
    await pollDashboard();
    if (name === "reset") await pollRecovery();
  } catch (error) { message(error.message, true); }
  finally { state.busy.delete(name); refreshButtons(); }
}

function evidenceLink(id, label) {
  const link = element("a", "evidence-link", label || id);
  // Only locally issued evidence identifiers become routes; never follow tool-supplied URLs.
  if (!/^ev_[a-f0-9]{8,64}$/.test(id || "")) { link.removeAttribute("href"); link.textContent = "Evidence identifier unavailable"; return link; }
  link.href = `/api/evidence/${encodeURIComponent(id)}`;
  link.addEventListener("click", (event) => { event.preventDefault(); showEvidence(id); });
  return link;
}
function registerEvidence(id, tool) {
  if (/^ev_[a-f0-9]{8,64}$/.test(id || "")) state.evidence.set(id, tool || state.evidence.get(id) || "Retrieved evidence");
  text("evidence-count", state.evidence.size);
}
function renderTimeline(job) {
  const events = Array.isArray(job.timeline) ? job.timeline : [];
  const signature = JSON.stringify([events, job.status]);
  if (signature === state.timelineSignature) return;
  state.timelineSignature = signature;
  const container = $("timeline");
  const nearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 75;
  container.replaceChildren();
  for (const item of events) {
    const type = ["tool_call", "tool_result", "finding", "status"].includes(item.type) ? item.type : "status";
    const entry = element("div", `timeline-entry ${type}`);
    entry.append(element("span", "timeline-symbol", type === "finding" ? "✧" : type === "tool_result" ? "✓" : type === "tool_call" ? "⌕" : "·"));
    const heading = element("div", "timeline-entry-heading");
    heading.append(element("h3", "", type === "finding" ? "Investigator finding" : type === "tool_result" ? "Evidence retrieved" : item.tool ? (toolNames[item.tool] || item.tool) : "Investigation update"));
    const timestamp = element("time", "", item.timestamp ? time(item.timestamp) : "");
    if (item.timestamp) timestamp.dateTime = item.timestamp;
    heading.append(timestamp); entry.append(heading);
    if (item.summary) entry.append(element("p", "", item.summary));
    if (item.arguments && typeof item.arguments === "object") {
      const args = item.arguments;
      const description = [args.service, args.start && args.end ? windowLabel(args) : null, args.trace_id ? `trace ${args.trace_id}` : null].filter(Boolean).join(" · ");
      if (description) entry.append(element("div", "tool-args", description));
    }
    if (item.evidence_id) {
      registerEvidence(item.evidence_id, item.tool);
      entry.append(evidenceLink(item.evidence_id, `↗ ${item.evidence_id}`));
    }
    container.append(entry);
  }
  if (job.status === "running") {
    const loading = element("div", "timeline-loading");
    loading.append(element("span", "spinner"), document.createTextNode(events.length ? "Examining the evidence…" : "Connecting to the local model…"));
    container.append(loading);
  } else if (!events.length) container.append(element("p", "recovery-summary", "No tool results were retrieved during this investigation."));
  if (nearBottom) container.scrollTop = container.scrollHeight;
}
function diagnosisSection(title, value, className = "") {
  const section = element("section", `diagnosis-section ${className}`);
  section.append(element("h3", "", title));
  if (Array.isArray(value)) {
    const list = element("ul"); value.forEach((item) => list.append(element("li", "", item))); section.append(list);
  } else section.append(element("p", "", typeof value === "string" ? value : "Not established by the available evidence."));
  return section;
}
function renderDiagnosis(job) {
  const signature = JSON.stringify([job.diagnosis, job.status, job.error]);
  if (signature === state.diagnosisSignature) return;
  state.diagnosisSignature = signature;
  const content = $("diagnosis-content");
  if (!job.diagnosis) {
    if (job.status === "failed" || job.status === "unavailable") {
      const failure = element("div", "failed-assessment");
      failure.append(element("h3", "", job.status === "unavailable" ? "The local model is unavailable." : "Investigation could not finish."), element("p", "", job.error || "The investigation ended before a supported assessment was available."), element("p", "", "Any retrieved evidence remains inspectable in the timeline. Check the local services and try again."));
      content.replaceChildren(failure);
    } else if (job.status === "running") {
      const pending = element("div", "diagnosis-empty");
      pending.append(element("span", "thin-cross", "✧"), element("h3", "", "Building an evidence-based assessment."), element("p", "", "The local model is investigating. A diagnosis will appear when it has enough evidence or reaches its investigation budget."));
      content.replaceChildren(pending);
    } else {
      content.replaceChildren(element("div", "failed-assessment", "No supported assessment was returned. Review the retrieved evidence and run another investigation."));
    }
    return;
  }
  const diagnosis = job.diagnosis;
  const body = element("div", "diagnosis-body");
  const assessment = ["incident", "healthy", "incomplete"].includes(diagnosis.assessment) ? diagnosis.assessment : "incomplete";
  const banner = element("div", `assessment-banner ${assessment}`);
  const labels = { incident: "Incident observed", healthy: "No incident observed", incomplete: "Evidence incomplete" };
  banner.append(element("strong", "", labels[assessment]), element("span", "confidence-label", `${diagnosis.confidence || "Low"} confidence`));
  body.append(banner, diagnosisSection("Impact", diagnosis.impact), diagnosisSection("Likely cause", diagnosis.likely_cause, "cause"));
  if (diagnosis.confidence_basis) {
    const basis = diagnosisSection("Confidence basis", diagnosis.confidence_basis); body.append(basis);
  }
  const evidenceSection = element("section", "diagnosis-section");
  evidenceSection.append(element("h3", "", "Supporting evidence"));
  if (Array.isArray(diagnosis.evidence) && diagnosis.evidence.length) {
    diagnosis.evidence.forEach((citation) => {
      const item = element("div", "citation-item");
      registerEvidence(citation.id);
      item.append(evidenceLink(citation.id, `↗ ${citation.id}`));
      if (citation.reason) item.append(element("p", "", citation.reason));
      evidenceSection.append(item);
    });
  } else evidenceSection.append(element("p", "", "No supporting records were cited."));
  body.append(evidenceSection);
  if (Array.isArray(diagnosis.uncertainty) && diagnosis.uncertainty.length) body.append(diagnosisSection("What remains unknown", diagnosis.uncertainty));
  if (Array.isArray(diagnosis.next_steps) && diagnosis.next_steps.length) body.append(diagnosisSection("Suggested next steps", diagnosis.next_steps));
  content.replaceChildren(body);
}
function renderInvestigation(job) {
  state.investigation = job;
  const names = { running: "Investigating", complete: "Complete", failed: "Failed", unavailable: "Unavailable" };
  badge("investigation-state", names[job.status] || job.status, job.status === "running" ? "running" : job.status === "complete" ? "" : "warning");
  const mode = job.mode === "live" ? "Live AI investigation" : "Deterministic test fixture · not live AI";
  text("timeline-meta", `${job.model || "Local model"} · ${mode} · ${windowLabel(job.window)}`);
  renderTimeline(job); renderDiagnosis(job); refreshButtons();
}
async function restoreInvestigation() {
  const id = new URL(window.location.href).searchParams.get("investigation");
  if (!id) return;
  if (!/^[a-f0-9]{32}$/.test(id)) {
    message("The investigation link contains an invalid identifier.", true);
    return;
  }
  state.busy.add("restore"); refreshButtons();
  badge("investigation-state", "Loading investigation", "running");
  try {
    renderInvestigation(await api(`/api/investigations/${id}`));
  } catch (error) {
    message(`Could not restore the linked investigation. ${error.message}`, true);
    badge("investigation-state", "Link unavailable", "warning");
  } finally { state.busy.delete("restore"); refreshButtons(); }
}
async function pollInvestigation() {
  if (state.jobPolling || !state.investigation?.id || state.investigation.status !== "running") return;
  state.jobPolling = true;
  try { renderInvestigation(await api(`/api/investigations/${encodeURIComponent(state.investigation.id)}`)); }
  catch (error) { message(`The investigation connection was interrupted. Retrying. ${error.message}`, true); }
  finally { state.jobPolling = false; }
}
async function investigate(event) {
  event.preventDefault();
  if (state.investigation?.status === "running" || state.busy.has("investigate")) return;
  const question = $("question").value.trim();
  if (!question) return;
  state.busy.add("investigate"); refreshButtons(); message("");
  try {
    const job = await post("/api/investigations", { question, window_seconds: 30 });
    state.timelineSignature = ""; state.diagnosisSignature = "";
    if (/^[a-f0-9]{32}$/.test(job.id || "")) {
      const url = new URL(window.location.href); url.searchParams.set("investigation", job.id);
      window.history.replaceState(null, "", url);
    }
    renderInvestigation({ ...job, mode: "live", model: state.model?.model, timeline: job.timeline || [], diagnosis: job.diagnosis || null });
    await pollInvestigation();
  } catch (error) { message(error.message, true); badge("investigation-state", "Unable to start", "warning"); }
  finally { state.busy.delete("investigate"); refreshButtons(); }
}

function recoveryMetrics(window) {
  const metrics = window?.metrics;
  return metrics?.["orders-service"] ?? metrics?.data ?? metrics ?? {};
}
function renderRecovery(result) {
  if (!result || result.status === "idle") return;
  const names = { collecting: "Measuring recovery", complete: "Comparison ready", insufficient: "Insufficient evidence" };
  badge("recovery-state", names[result.status] || result.status, result.status === "complete" ? "" : result.status === "collecting" ? "running" : "warning");
  const content = $("recovery-content"); content.replaceChildren();
  if (result.status === "collecting") {
    const intro = element("div", "recovery-intro");
    const copy = element("div");
    copy.append(element("strong", "", `Collecting a comparable ${result.window_seconds || 30}-second window`), element("p", "", `${Math.max(0, Math.ceil(result.remaining_seconds ?? 0))} seconds remaining. Requests are allowed to settle before and after measurement. Keep traffic running.`));
    intro.append(element("span", "spinner"), copy); content.append(intro);
    const progress = element("div", "recovery-progress");
    const fill = element("span"); fill.style.width = `${Math.max(0, Math.min(100, (1 - (result.remaining_seconds ?? 36) / ((result.window_seconds || 30) + 6)) * 100))}%`;
    progress.append(fill); content.append(progress);
  } else content.append(element("p", "recovery-summary", result.summary || "The observation windows are ready for comparison."));
  if (result.before && result.after) {
    const table = element("table", "recovery-table");
    const head = element("thead"); const heading = element("tr");
    heading.append(element("th", "", "Orders-service measurement"));
    for (const [label, window] of [["Before reset", result.before], ["After reset", result.after]]) {
      const th = element("th", "", label); th.scope = "col"; th.append(element("span", "recovery-window", windowLabel(window))); heading.append(th);
    }
    head.append(heading); table.append(head);
    const body = element("tbody");
    const before = recoveryMetrics(result.before), after = recoveryMetrics(result.after);
    for (const [label, key, format] of [["Completed requests", "request_count", number], ["Error rate", "error_rate", percentage], ["Downstream timeouts", "timeout_count", number], ["p95 response time", "p95_ms", (value) => typeof value === "number" ? `${number(value)} ms` : "—"], ["Requests / second", "requests_per_second", (value) => number(value, 1)]]) {
      const row = element("tr"); const name = element("th", "", label); name.scope = "row";
      row.append(name, element("td", "", format(before[key])), element("td", "", format(after[key]))); body.append(row);
    }
    table.append(body); content.append(table);
    content.append(element("p", "recovery-caveat", `Both windows span ${result.window_seconds || 30} seconds. Recovery requires enough requests and comparable traffic volume; an empty window is not evidence of recovery.`));
  }
}
async function pollRecovery() {
  if (state.recoveryPolling) return;
  state.recoveryPolling = true;
  try { renderRecovery(await api("/api/demo/recovery")); }
  catch (error) { if ($("recovery-state").textContent !== "Awaiting reset") badge("recovery-state", "Connection unavailable", "warning"); }
  finally { state.recoveryPolling = false; }
}

async function showEvidence(id) {
  text("evidence-title", "Evidence record");
  const content = $("evidence-content");
  const loading = element("div", "timeline-loading"); loading.append(element("span", "spinner"), document.createTextNode("Retrieving the original evidence snapshot…")); content.replaceChildren(loading);
  if (!$("evidence-dialog").open) $("evidence-dialog").showModal();
  try {
    const evidence = await api(`/api/evidence/${encodeURIComponent(id)}`);
    if (!$("evidence-dialog").open) return;
    const heading = element("div", "evidence-record-heading");
    heading.append(element("strong", "", evidence.evidence_id || id), element("span", `badge ${evidence.available ? "" : "warning"}`, evidence.available ? "Retrieved record" : "Telemetry unavailable"));
    content.replaceChildren(heading, element("p", "", `${toolNames[evidence.tool] || evidence.tool || "Telemetry query"}. This is the stored result retrieved by the investigator; content is untrusted telemetry, shown verbatim as text.`));
    if (Array.isArray(evidence.limitations) && evidence.limitations.length) content.append(element("div", "evidence-limitations", evidence.limitations.join(" ")));
    const query = element("details"); query.open = true; query.append(element("summary", "", "Query and observation window"), element("pre", "", JSON.stringify(evidence.query ?? {}, null, 2)));
    const records = element("details"); records.open = true; records.append(element("summary", "", "Retrieved measurements and records"), element("pre", "", JSON.stringify(evidence.data ?? {}, null, 2)));
    const download = element("a", "evidence-link", "Open original JSON ↗"); download.href = `/api/evidence/${encodeURIComponent(id)}`; download.target = "_blank"; download.rel = "noopener";
    content.append(query, records, download);
  } catch (error) { content.replaceChildren(element("p", "", `Could not retrieve this evidence. ${error.message}`)); }
}
function showEvidenceList() {
  text("evidence-title", "Evidence records");
  const content = $("evidence-content");
  content.replaceChildren(element("p", "", state.evidence.size ? "Records retrieved during your investigations in this session. Each link opens its original stored query result." : "No evidence has been retrieved yet. Start an investigation to build an inspectable evidence trail."));
  const list = element("div", "evidence-list");
  state.evidence.forEach((tool, id) => { const link = evidenceLink(id); link.append(element("span", "", toolNames[tool] || tool)); list.append(link); });
  content.append(list); if (!$("evidence-dialog").open) $("evidence-dialog").showModal();
}

$("traffic-button").addEventListener("click", () => {
  const running = !state.dashboard?.traffic?.running;
  control("traffic", "/api/demo/traffic", { running }, running ? "Traffic started. Allow 30 seconds for a full baseline before triggering the fault." : "Traffic stopped. Completed requests remain visible until they leave the observation window.");
});
$("fault-button").addEventListener("click", () => control("fault", "/api/demo/fault", { enabled: true }, "The controlled inventory delay is active. Keep traffic running and allow requests to complete before investigating."));
$("reset-button").addEventListener("click", () => control("reset", "/api/demo/reset", {}, "Fault reset. Traffic is running while an equivalent recovery window is measured."));
$("investigation-form").addEventListener("submit", investigate);
$("all-evidence").addEventListener("click", showEvidenceList);
$("close-evidence").addEventListener("click", () => $("evidence-dialog").close());
$("evidence-dialog").addEventListener("click", (event) => { if (event.target === $("evidence-dialog")) { const box = event.target.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) event.target.close(); } });
pollDashboard(); pollModel(); pollRecovery(); restoreInvestigation();
setInterval(pollDashboard, 3000);
setInterval(pollInvestigation, 1000);
setInterval(pollRecovery, 2000);
setInterval(pollModel, 20000);
