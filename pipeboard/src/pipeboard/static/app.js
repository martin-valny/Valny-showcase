// pipeboard UI. The Run form is built entirely from GET /api/schema, and no
// parameter names appear in this file. Edit schema/pipeline.yaml and reload.

const $ = (sel) => document.querySelector(sel);
const api = async (path, opts = {}) => {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = res.headers.get("content-type")?.includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new Error(body?.detail || res.statusText);
  return body;
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

let schema = null;
let selectedJob = null;
let logOffset = 0;
let logTimer = null;

// ---------------------------------------------------------------- tabs

function showTab(name) {
  document.querySelectorAll("[role=tab]").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((s) => (s.hidden = s.id !== `tab-${name}`));
  if (name === "jobs") refreshJobs();
  if (name === "report") refreshReports();
}
document.querySelectorAll("[role=tab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

// ---------------------------------------------------------------- run form

function inputFor(p) {
  const id = `param-${p.name}`;
  let input;
  if (p.type === "bool") {
    input = Object.assign(document.createElement("input"), { type: "checkbox", checked: !!p.default });
  } else if (p.type === "choice") {
    input = document.createElement("select");
    (p.options || []).forEach((o) => input.append(new Option(o, o, false, o === p.default)));
  } else {
    input = Object.assign(document.createElement("input"), {
      type: "number",
      value: p.default,
      step: p.step ?? (p.type === "int" ? 1 : "any"),
      required: true,
    });
    if (p.min !== undefined) input.min = p.min;
    if (p.max !== undefined) input.max = p.max;
  }
  input.id = id;
  input.name = p.name;
  input.dataset.type = p.type;

  const wrap = document.createElement("div");
  wrap.className = "field";
  const range = p.min !== undefined || p.max !== undefined ? ` <span class="muted">[${esc(p.min ?? "…")} – ${esc(p.max ?? "…")}]</span>` : "";
  wrap.innerHTML = `<label for="${esc(id)}">${esc(p.label || p.name)} <code>${esc(p.type)}</code>${range}</label>`;
  wrap.append(input);
  if (p.help) wrap.insertAdjacentHTML("beforeend", `<p class="help">${esc(p.help)}</p>`);
  return wrap;
}

function readForm() {
  const params = {};
  for (const p of schema.parameters) {
    const el = document.getElementById(`param-${p.name}`);
    if (p.type === "bool") params[p.name] = el.checked;
    else if (p.type === "choice") params[p.name] = el.value;
    else params[p.name] = el.value === "" ? null : Number(el.value);
  }
  return params;
}

async function loadForm() {
  schema = await api("/api/schema");
  const fields = $("#fields");
  fields.replaceChildren(...schema.parameters.map(inputFor));
}

async function loadDataStatus() {
  const s = await api("/api/data/status");
  const banner = $("#data-status");
  const select = $("#sample_col_select");
  if (!s.exists) {
    banner.className = "banner warn";
    banner.innerHTML = `Data not found at <code>${esc(s.path)}</code>. Run <code>python scripts/fetch_data.py</code>, then reload.`;
    $("#submit").disabled = true;
    $("#setup").hidden = true;
    return;
  }
  banner.className = "banner ok";
  banner.innerHTML = `Input: <code>${esc(s.path)}</code> · ${s.n_obs.toLocaleString()} cells × ${s.n_vars.toLocaleString()} genes · ${(s.size_bytes / 1e6).toFixed(1)} MB`;
  $("#submit").disabled = false;
  select.replaceChildren(new Option("(none)", ""));
  if (!s.sample_columns.length) {
    select.disabled = true;
    $("#setup-help").textContent = "No sample/group column found in obs, so this step is skipped.";
  } else {
    s.sample_columns.forEach((c) => select.append(new Option(`${c.name} (${c.n_values} values)`, c.name)));
  }
}

$("#run-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("#form-error");
  err.hidden = true;
  $("#submit").disabled = true;
  try {
    const job = await api("/api/jobs", {
      method: "POST",
      body: JSON.stringify({ params: readForm(), sample_col: $("#sample_col_select").value || null }),
    });
    selectJob(job.id);
    showTab("jobs");
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
  } finally {
    $("#submit").disabled = false;
  }
});

// ---------------------------------------------------------------- jobs

const fmt = (t) => (t ? new Date(t).toLocaleTimeString() : "—");
const badge = (s) => `<span class="status ${s}">${s}</span>`;

async function refreshJobs() {
  const jobs = await api("/api/jobs");
  $("#jobs-empty").hidden = jobs.length > 0;
  $("#jobs-table").hidden = jobs.length === 0;
  $("#jobs-table tbody").innerHTML = jobs
    .map(
      (j) => `<tr data-id="${j.id}" class="${j.id === selectedJob ? "selected" : ""}">
        <td><code>${esc(j.id)}</code></td><td>${badge(esc(j.status))}</td><td>${fmt(j.started_at)}</td><td>${fmt(j.ended_at)}</td>
        <td><button class="link">logs</button></td></tr>`
    )
    .join("");
  document.querySelectorAll("#jobs-table tbody tr").forEach((tr) => tr.addEventListener("click", () => selectJob(tr.dataset.id)));
  if (selectedJob) updateLogHeader(jobs.find((j) => j.id === selectedJob));
}

function updateLogHeader(job) {
  if (!job) return;
  $("#log-status").outerHTML = `<span id="log-status" class="status ${job.status}">${job.status}</span>`;
  const active = job.status === "queued" || job.status === "running";
  $("#cancel-btn").hidden = !active;
  $("#open-report-btn").hidden = !job.has_report;
  $("#log-error").hidden = !job.error;
  $("#log-error").textContent = job.error || "";
}

function selectJob(id) {
  selectedJob = id;
  logOffset = 0;
  $("#log").textContent = "";
  $("#log-title").textContent = id;
  $("#log-panel").hidden = false;
  clearTimeout(logTimer);
  pollLog();
  refreshJobs();
}

async function pollLog() {
  const id = selectedJob;
  try {
    const chunk = await api(`/api/jobs/${id}/logs?offset=${logOffset}`);
    if (id !== selectedJob) return;
    if (chunk.text) {
      const pre = $("#log");
      const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4;
      pre.textContent += chunk.text;
      if (atBottom) pre.scrollTop = pre.scrollHeight;
    }
    logOffset = chunk.offset;
    if (chunk.done) {
      refreshJobs();
      return;
    }
  } catch (ex) {
    $("#log-error").textContent = ex.message;
    $("#log-error").hidden = false;
  }
  logTimer = setTimeout(pollLog, 1000);
}

$("#cancel-btn").addEventListener("click", async () => {
  await api(`/api/jobs/${selectedJob}`, { method: "DELETE" }).catch((ex) => alert(ex.message));
  refreshJobs();
});
$("#open-report-btn").addEventListener("click", () => {
  showTab("report");
  $("#report-select").value = selectedJob;
  showReport(selectedJob);
});

// ---------------------------------------------------------------- report

async function refreshReports() {
  const jobs = (await api("/api/jobs")).filter((j) => j.has_report);
  const select = $("#report-select");
  const keep = select.value || selectedJob;
  select.replaceChildren(...jobs.map((j) => new Option(`${j.id} · ${j.status}`, j.id)));
  $("#report-empty").hidden = jobs.length > 0;
  $("#report-frame").hidden = jobs.length === 0;
  $("#report-download").hidden = jobs.length === 0;
  select.hidden = jobs.length === 0;
  if (jobs.length) showReport(jobs.some((j) => j.id === keep) ? keep : jobs[0].id);
}

function showReport(id) {
  $("#report-select").value = id;
  $("#report-frame").src = `/api/jobs/${id}/report`;
  $("#report-download").href = `/api/jobs/${id}/report?download=1`;
}
$("#report-select").addEventListener("change", (e) => showReport(e.target.value));

// ---------------------------------------------------------------- boot

setInterval(() => !$("#tab-jobs").hidden && refreshJobs(), 2000);
loadForm().then(loadDataStatus).catch((ex) => {
  $("#data-status").className = "banner warn";
  $("#data-status").textContent = `Could not load the form: ${ex.message}`;
});
