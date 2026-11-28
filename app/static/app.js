const API = "/api/v1";

const state = {
  userToken: localStorage.getItem("lumenpilotUserToken") || "",
  sessionToken: localStorage.getItem("lumenpilotSessionToken") || "",
  sessionId: localStorage.getItem("lumenpilotSessionId") || "",
  account: JSON.parse(localStorage.getItem("lumenpilotAccount") || "null"),
  currentView: "chat"
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(element.timer);
  element.timer = setTimeout(() => element.classList.remove("show"), 2400);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  })[character]);
}

async function api(path, options = {}, token = "") {
  const headers = { ...(options.headers || {}) };
  if (options.body && !(options.body instanceof URLSearchParams)) {
    headers["Content-Type"] = "application/json";
  }
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${API}${path}`, { ...options, headers });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = payload?.detail || payload?.error || `请求失败 ${response.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
}

function setAuthError(message = "") {
  $("#authError").textContent = message;
}

function switchAuthTab(register) {
  $("#loginTab").classList.toggle("active", !register);
  $("#registerTab").classList.toggle("active", register);
  $("#loginForm").classList.toggle("hidden", register);
  $("#registerForm").classList.toggle("hidden", !register);
  setAuthError();
}

function storeAccount(account) {
  state.account = account;
  localStorage.setItem("lumenpilotAccount", JSON.stringify(account));
}

async function login(email, password) {
  const body = new URLSearchParams({ email, password, grant_type: "password" });
  const data = await api("/auth/login", { method: "POST", body });
  state.userToken = data.access_token;
  localStorage.setItem("lumenpilotUserToken", state.userToken);
  storeAccount({ user_id: data.user_id, email: data.email, username: data.username, role: data.role });
  await enterWorkspace();
}

async function register(email, username, password) {
  const data = await api("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, username, password })
  });
  state.userToken = data.token.access_token;
  localStorage.setItem("lumenpilotUserToken", state.userToken);
  storeAccount({ user_id: data.id, email: data.email, username: data.username, role: data.role });
  await enterWorkspace();
}

async function createSession() {
  const session = await api("/auth/session", { method: "POST" }, state.userToken);
  state.sessionId = session.session_id;
  state.sessionToken = session.token.access_token;
  localStorage.setItem("lumenpilotSessionId", state.sessionId);
  localStorage.setItem("lumenpilotSessionToken", state.sessionToken);
  renderSession();
}

function renderSession() {
  $("#sessionIdText").textContent = state.sessionId ? state.sessionId.slice(0, 18) + "..." : "登录后自动创建";
  $("#sessionShort").textContent = state.sessionId ? state.sessionId.slice(0, 8) : "尚未创建";
}

function renderAccount() {
  const account = state.account;
  if (!account) return;
  $("#accountName").textContent = account.username || account.email;
  $("#accountRole").textContent = account.role;
  $("#accountAvatar").textContent = (account.username || account.email || "U").slice(0, 1).toUpperCase();
  $("#adminNav").classList.toggle("hidden", account.role !== "ADMIN");
}

async function enterWorkspace() {
  $("#authScreen").classList.add("hidden");
  $("#workspace").classList.remove("hidden");
  renderAccount();
  if (!state.sessionToken) await createSession();
  renderSession();
  await checkHealth();
  if (state.account?.role === "ADMIN") loadAdmin();
}

async function restoreSession() {
  if (!state.userToken) return false;
  try {
    const account = await api("/auth/me", {}, state.userToken);
    storeAccount(account);
    await enterWorkspace();
    return true;
  } catch {
    clearSession();
    return false;
  }
}

function clearSession() {
  state.userToken = "";
  state.sessionToken = "";
  state.sessionId = "";
  state.account = null;
  localStorage.removeItem("lumenpilotUserToken");
  localStorage.removeItem("lumenpilotSessionToken");
  localStorage.removeItem("lumenpilotSessionId");
  localStorage.removeItem("lumenpilotAccount");
  $("#workspace").classList.add("hidden");
  $("#authScreen").classList.remove("hidden");
}

async function checkHealth() {
  try {
    const response = await fetch("/health");
    const data = await response.json();
    const online = data.status === "healthy";
    $("#healthDot").classList.toggle("offline", !online);
    $("#healthText").textContent = online ? "服务正常" : "服务异常";
  } catch {
    $("#healthDot").classList.add("offline");
    $("#healthText").textContent = "无法连接";
  }
}

function renderReflectionTrace(trace) {
  if (!trace) return "";
  const labels = {
    passed: "质量检查通过",
    corrected: `已自动修正 ${trace.attempts || 1} 次`,
    unresolved: "质量检查未通过",
    retry: "正在按质量反馈修正",
    not_run: "质量检查未执行"
  };
  const icons = {
    passed: "✓",
    corrected: "↻",
    unresolved: "!",
    retry: "↻",
    not_run: "–"
  };
  const status = labels[trace.status] ? trace.status : "not_run";
  const reason = trace.reason
    ? `<small>${escapeHtml(trace.reason)}</small>`
    : "";
  return `
    <div class="reflection-badge ${status}">
      <b><i>${icons[status]}</i>${labels[status]}</b>
      ${reason}
    </div>`;
}

function appendMessage(role, content, extraClass = "", reflection = null) {
  const article = document.createElement("article");
  article.className = `message ${role} ${extraClass}`.trim();
  article.innerHTML = `
    <div class="message-avatar">${role === "user" ? "ME" : "LP"}</div>
    <div class="message-body">
      <span>${role === "user" ? state.account?.username || "你" : "LumenPilot"}</span>
      <p>${escapeHtml(content)}</p>
      ${role === "assistant" ? renderReflectionTrace(reflection) : ""}
    </div>`;
  $("#messageList").appendChild(article);
  $("#messageList").scrollTop = $("#messageList").scrollHeight;
  return article;
}

async function sendMessage(content) {
  const text = content.trim();
  if (!text) return;
  if (!state.sessionToken) await createSession();
  appendMessage("user", text);
  const loading = appendMessage("assistant", "正在查询数据并整理分析", "loading");
  $("#sendButton").disabled = true;
  try {
    const data = await api("/chatbot/chat", {
      method: "POST",
      body: JSON.stringify({ messages: [{ role: "user", content: text }] })
    }, state.sessionToken);
    loading.remove();
    const assistantMessages = (data.messages || []).filter((message) => message.role === "assistant");
    const reply = assistantMessages.at(-1)?.content || "Agent 未返回文本结果";
    const pending = /确认|create_ops_task|question/i.test(reply);
    appendMessage("assistant", reply, pending ? "pending" : "", data.reflection);
  } catch (error) {
    loading.remove();
    appendMessage("assistant", `请求失败：${error.message}`, "pending");
  } finally {
    $("#sendButton").disabled = false;
  }
}

function switchView(view) {
  state.currentView = view;
  $$(".view").forEach((element) => element.classList.remove("active"));
  $(`#${view}View`).classList.add("active");
  $$(".nav-item[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  const admin = view === "admin";
  $("#pageKicker").textContent = admin ? "ADMIN CONTROL ROOM" : "OPERATIONS COPILOT";
  $("#pageTitle").textContent = admin ? "管理控制台" : "智能分析";
  if (admin) loadAdmin();
}

async function loadAdmin() {
  if (state.account?.role !== "ADMIN") return;
  $("#adminNotice").classList.add("hidden");
  try {
    const [overview, users, tasks] = await Promise.all([
      api("/admin/overview", {}, state.userToken),
      api("/admin/users", {}, state.userToken),
      api("/admin/tasks", {}, state.userToken).catch(() => [])
    ]);
    $("#metricAccounts").textContent = overview.accounts ?? users.length;
    $("#metricAdmins").textContent = overview.admins ?? "--";
    $("#metricSessions").textContent = overview.sessions ?? "--";
    $("#metricTasks").textContent = overview.pending_tasks ?? "--";
    renderUsers(users);
    renderTasks(tasks);
    if (!overview.lumafeed_online) {
      $("#adminNotice").textContent = "LumaFeed 任务接口暂未连接，聊天分析和其他账号功能不受影响。";
      $("#adminNotice").classList.remove("hidden");
    }
  } catch (error) {
    $("#adminNotice").textContent = error.message;
    $("#adminNotice").classList.remove("hidden");
  }
}

function renderUsers(users) {
  $("#userTableBody").innerHTML = users.map((user) => `
    <tr>
      <td><b>${escapeHtml(user.username || "-")}</b></td>
      <td>${escapeHtml(user.email)}</td>
      <td><span class="role-tag ${user.role === "ADMIN" ? "admin" : ""}">${escapeHtml(user.role)}</span></td>
      <td>${user.last_login_at ? escapeHtml(new Date(user.last_login_at).toLocaleString()) : "尚未登录"}</td>
    </tr>`).join("");
}

function renderTasks(tasks) {
  $("#taskList").innerHTML = tasks.length ? tasks.map((task) => `
    <article class="task-item">
      <b>${escapeHtml(task.title)}</b>
      <p>${escapeHtml(task.description || "无任务描述")}</p>
      <small>${escapeHtml(task.status)} · ${escapeHtml(task.priority)} · ${escapeHtml(task.createTime || "")}</small>
    </article>`).join("") : '<p class="empty-state">当前没有运营任务。可在对话中测试人工确认后创建。</p>';
}

async function loadMetrics() {
  try {
    const data = await api("/admin/metrics?days=7", {}, state.userToken);
    const values = [
      ["用户总数", data.totalUsers],
      ["笔记总数", data.totalBlogs],
      ["点赞总数", data.totalLikes],
      ["评论总数", data.totalComments]
    ];
    $("#metricsSnapshot").innerHTML = values.map(([label, value]) => `
      <div class="snapshot-item"><span>${label}</span><b>${Number(value || 0)}</b></div>`).join("");
  } catch (error) {
    $("#metricsSnapshot").innerHTML = `<p class="empty-state">${escapeHtml(error.message)}</p>`;
  }
}

function initEvents() {
  $("#loginTab").addEventListener("click", () => switchAuthTab(false));
  $("#registerTab").addEventListener("click", () => switchAuthTab(true));
  $("#loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    setAuthError();
    try {
      await login($("#loginEmail").value.trim(), $("#loginPassword").value);
    } catch (error) {
      setAuthError(error.message);
    }
  });
  $("#registerForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    setAuthError();
    try {
      await register($("#registerEmail").value.trim(), $("#registerUsername").value.trim(), $("#registerPassword").value);
    } catch (error) {
      setAuthError(error.message);
    }
  });
  $$("[data-test-email]").forEach((button) => button.addEventListener("click", async () => {
    $("#loginEmail").value = button.dataset.testEmail;
    $("#loginPassword").value = button.dataset.testPassword;
    setAuthError();
    try {
      await login(button.dataset.testEmail, button.dataset.testPassword);
    } catch (error) {
      setAuthError(error.message);
    }
  }));
  $("#chatForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("#chatInput");
    const content = input.value;
    input.value = "";
    await sendMessage(content);
  });
  $("#chatInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $("#chatForm").requestSubmit();
    }
  });
  $$("[data-prompt]").forEach((button) => button.addEventListener("click", () => sendMessage(button.dataset.prompt)));
  $("#newSessionButton").addEventListener("click", async () => {
    await createSession();
    $("#messageList").innerHTML = "";
    appendMessage("assistant", "已创建新的独立会话。这个会话拥有自己的上下文和人工确认状态。");
  });
  $("#clearChatButton").addEventListener("click", async () => {
    try {
      await api("/chatbot/messages", { method: "DELETE" }, state.sessionToken);
      $("#messageList").innerHTML = "";
      appendMessage("assistant", "当前会话历史已清空。");
    } catch (error) {
      toast(error.message);
    }
  });
  $$(".nav-item[data-view]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  $$("[data-admin-load]").forEach((button) => button.addEventListener("click", () => {
    if (button.dataset.adminLoad === "users") loadAdmin();
    if (button.dataset.adminLoad === "tasks") loadAdmin();
    if (button.dataset.adminLoad === "metrics") loadMetrics();
  }));
  $("#refreshButton").addEventListener("click", () => {
    if (state.currentView === "admin") loadAdmin();
    else checkHealth();
  });
  $("#logoutButton").addEventListener("click", clearSession);
}

initEvents();
restoreSession();
