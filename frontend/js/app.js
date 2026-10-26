// DeadlineRadar frontend: auth, task list, and live risk preview.

const $ = (selector) => document.querySelector(selector);
const state = { csrf: null, user: null, view: "all", search: "", sort: "risk", page: 1, editing: null };

// ---------- API ----------

async function api(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (method !== "GET" && state.csrf) headers["X-CSRF-Token"] = state.csrf;
  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 && state.user && !path.startsWith("/api/auth/")) {
    showAuth();
  }
  if (!response.ok) {
    const error = new Error(data.error || `Request failed (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return data;
}

// ---------- helpers ----------

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function dueLabel(task) {
  const days = task.days_until_due;
  if (days === null || days === undefined) return "No due date";
  if (days < 0) return `${-days}d overdue`;
  if (days === 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  return `Due in ${days}d`;
}

function formatMinutes(minutes) {
  if (minutes < 60) return `${minutes}m`;
  return `${+(minutes / 60).toFixed(1)}h`;
}

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

// ---------- auth ----------

let authMode = "login";

function setAuthMode(mode) {
  authMode = mode;
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("is-active", tab.dataset.mode === mode));
  document.querySelector("[data-register-only]").hidden = mode !== "register";
  $("#auth-form").elements.password.autocomplete = mode === "register" ? "new-password" : "current-password";
  $("#auth-submit").textContent = mode === "register" ? "Create account" : "Sign in";
  $("#auth-error").textContent = "";
}

function showAuth() {
  state.user = null;
  state.csrf = null;
  $("#app-view").hidden = true;
  $("#auth-view").hidden = false;
}

function showApp({ user, csrf_token }) {
  state.user = user;
  state.csrf = csrf_token;
  $("#user-name").textContent = user.display_name;
  $("#auth-view").hidden = true;
  $("#app-view").hidden = false;
  loadTasks();
}

$("#auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const body = { email: form.elements.email.value.trim(), password: form.elements.password.value };
  if (authMode === "register") {
    body.display_name = form.elements.display_name.value.trim();
    body.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  }
  $("#auth-submit").disabled = true;
  try {
    showApp(await api(`/api/auth/${authMode}`, { method: "POST", body }));
    form.reset();
  } catch (error) {
    $("#auth-error").textContent = error.message;
  } finally {
    $("#auth-submit").disabled = false;
  }
});

document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => setAuthMode(tab.dataset.mode)));

$("#logout").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" }).catch(() => {});
  showAuth();
});

// ---------- task list ----------

function renderTask(task) {
  const done = task.status === "completed";
  const band = done ? "done" : task.risk_band || "low";
  const score = done ? "✓" : task.risk_score ?? "–";
  const manual = task.priority_source === "manual" ? ' title="Set manually"' : "";
  return `
    <li class="task ${done ? "is-done" : ""}" data-id="${task.id}">
      <input type="checkbox" class="check" ${done ? "checked" : ""} aria-label="Mark ${escapeHtml(task.title)} complete">
      <button class="task-main" type="button" data-action="edit">
        <span class="task-title">${escapeHtml(task.title)}</span>
        <span class="task-meta">
          <span class="${task.is_overdue ? "overdue" : ""}">${dueLabel(task)}</span>
          · ${escapeHtml(task.category)} · ${formatMinutes(task.effort_minutes)}
        </span>
      </button>
      <span class="priority priority-${task.priority.toLowerCase()}"${manual}>${task.priority}${task.priority_source === "manual" ? "*" : ""}</span>
      <span class="risk risk-${band}" title="Risk score">${score}</span>
      <button class="icon-btn" type="button" data-action="delete" aria-label="Delete ${escapeHtml(task.title)}">✕</button>
    </li>`;
}

async function loadTasks() {
  const params = new URLSearchParams({ view: state.view, sort: state.sort, page: state.page, page_size: 25 });
  if (state.search) params.set("search", state.search);
  $("#list-error").textContent = "";
  try {
    const data = await api(`/api/tasks?${params}`);
    if (data.pages && state.page > data.pages) {
      state.page = data.pages;
      return loadTasks();
    }
    $("#task-list").innerHTML = data.tasks.map(renderTask).join("");
    $("#empty").hidden = data.tasks.length > 0;
    for (const [key, value] of Object.entries(data.counts)) {
      const badge = document.querySelector(`[data-count="${key}"]`);
      if (badge) badge.textContent = value;
    }
    document.querySelectorAll("#views button").forEach((b) => b.classList.toggle("is-active", b.dataset.view === state.view));
    $("#pager").hidden = data.pages <= 1;
    $("#page-info").textContent = `Page ${data.page} of ${data.pages}`;
    $("#prev").disabled = data.page <= 1;
    $("#next").disabled = data.page >= data.pages;
    state.tasks = data.tasks;
  } catch (error) {
    if (error.status !== 401) $("#list-error").textContent = error.message;
  }
}

$("#views").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-view]");
  if (!button) return;
  state.view = button.dataset.view;
  state.page = 1;
  loadTasks();
});

$("#search").addEventListener(
  "input",
  debounce((event) => {
    state.search = event.target.value.trim();
    state.page = 1;
    loadTasks();
  }, 250),
);

$("#sort").addEventListener("change", (event) => {
  state.sort = event.target.value;
  loadTasks();
});

$("#prev").addEventListener("click", () => { state.page -= 1; loadTasks(); });
$("#next").addEventListener("click", () => { state.page += 1; loadTasks(); });

$("#task-list").addEventListener("click", async (event) => {
  const item = event.target.closest(".task");
  if (!item) return;
  const id = Number(item.dataset.id);
  try {
    if (event.target.matches(".check")) {
      await api(`/api/tasks/${id}/complete`, { method: "PATCH", body: { completed: event.target.checked } });
      loadTasks();
    } else if (event.target.closest("[data-action=delete]")) {
      const task = state.tasks.find((t) => t.id === id);
      if (confirm(`Delete "${task.title}"?`)) {
        await api(`/api/tasks/${id}`, { method: "DELETE" });
        loadTasks();
      }
    } else if (event.target.closest("[data-action=edit]")) {
      openDialog(state.tasks.find((t) => t.id === id));
    }
  } catch (error) {
    $("#list-error").textContent = error.message;
  }
});

// ---------- add / edit dialog + live risk preview ----------

const dialog = $("#task-dialog");
const taskForm = $("#task-form");

function openDialog(task = null) {
  state.editing = task;
  taskForm.reset();
  $("#dialog-title").textContent = task ? "Edit task" : "New task";
  $("#task-error").textContent = "";
  if (task) {
    taskForm.elements.title.value = task.title;
    taskForm.elements.description.value = task.description;
    taskForm.elements.category.value = task.category;
    taskForm.elements.due_date.value = task.due_date || "";
    taskForm.elements.effort_minutes.value = task.effort_minutes;
    taskForm.elements.priority.value = task.priority_source === "manual" ? task.priority : "";
  }
  dialog.showModal();
  taskForm.elements.title.focus();
  refreshPreview();
}

function formPayload() {
  return {
    title: taskForm.elements.title.value.trim(),
    description: taskForm.elements.description.value.trim(),
    category: taskForm.elements.category.value,
    due_date: taskForm.elements.due_date.value || null,
    effort_minutes: Number(taskForm.elements.effort_minutes.value) || 60,
    priority: taskForm.elements.priority.value || null,
  };
}

function renderPreview({ assessment, rescue_plan }) {
  const signals = assessment.signals
    .filter((s) => s.impact !== 0)
    .map(
      (s) => `<li><span class="impact ${s.impact > 0 ? "up" : "down"}">${s.impact > 0 ? "+" : ""}${s.impact}</span>
        <span><strong>${escapeHtml(s.label)}</strong><br><span class="muted">${escapeHtml(s.detail)}</span></span></li>`,
    )
    .join("");
  const steps = rescue_plan
    .map(
      (step) => `<li><strong>${escapeHtml(step.title)}</strong> <span class="when">${escapeHtml(step.when)}</span>
        <br><span class="muted">${escapeHtml(step.detail)}</span></li>`,
    )
    .join("");
  return `
    <div class="score-line">
      <span class="risk risk-${assessment.risk_band} risk-lg">${assessment.risk_score}</span>
      <div><strong>${escapeHtml(assessment.risk_label)} risk</strong> · suggests ${assessment.priority}
        <br><span class="muted">${escapeHtml(assessment.headline)}</span></div>
    </div>
    ${signals ? `<h3>Why</h3><ul class="signals">${signals}</ul>` : ""}
    ${steps ? `<h3>Rescue plan</h3><ol class="plan">${steps}</ol>` : ""}`;
}

let previewSeq = 0;
const refreshPreview = debounce(async () => {
  const seq = ++previewSeq;
  const payload = formPayload();
  if (!payload.title) {
    $("#preview-body").innerHTML = '<span class="muted">Add a title and due date to see the risk.</span>';
    return;
  }
  if (state.editing) payload.task_id = state.editing.id;
  try {
    const data = await api("/api/risk/preview", { method: "POST", body: payload });
    if (seq === previewSeq) $("#preview-body").innerHTML = renderPreview(data);
  } catch (error) {
    if (seq === previewSeq) $("#preview-body").innerHTML = `<span class="form-error">${escapeHtml(error.message)}</span>`;
  }
}, 300);

taskForm.addEventListener("input", refreshPreview);
$("#cancel-task").addEventListener("click", () => dialog.close());

taskForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = formPayload();
  if (!payload.title) {
    $("#task-error").textContent = "Title is required.";
    return;
  }
  // On create, an empty priority means auto; omit it so the server picks it.
  if (!state.editing && payload.priority === null) delete payload.priority;
  try {
    if (state.editing) {
      await api(`/api/tasks/${state.editing.id}`, { method: "PATCH", body: payload });
    } else {
      await api("/api/tasks", { method: "POST", body: payload });
    }
    dialog.close();
    loadTasks();
  } catch (error) {
    $("#task-error").textContent = error.message;
  }
});

$("#new-task").addEventListener("click", () => openDialog());

// ---------- boot ----------

api("/api/auth/me")
  .then(showApp)
  .catch(showAuth);
