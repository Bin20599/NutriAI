const API_BASE = window.location.origin;
const $ = (selector) => document.querySelector(selector);

let profile = JSON.parse(localStorage.getItem("nutriai_profile") || "{}");
let userId = localStorage.getItem("nutriai_user_id") || crypto.randomUUID();
let conversationId = null;
let currentLocalChatId = null;
let chatHistory = JSON.parse(localStorage.getItem("nutriai_chat_history") || "[]");
localStorage.setItem("nutriai_user_id", userId);

function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.style.display = "block";
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => (el.style.display = "none"), 2600);
}

function scrollChat() {
  const chat = $("#chat");
  chat.scrollTop = chat.scrollHeight;
}

function addMessage(role, text, meta = "", sources = [], saveHistory = true) {
  $("#welcome")?.remove();
  const row = document.createElement("div");
  row.className = `message ${role}`;
  const sourceHtml = sources.length
    ? `<div class="sources">${sources.map((s) => `<span class="source-chip">Nguồn: ${escapeHtml(s.title || s)}</span>`).join("")}</div>`
    : "";
  row.innerHTML = `<div><div class="bubble"></div>${sourceHtml}<div class="meta"></div></div>`;
  row.querySelector(".bubble").textContent = text;
  row.querySelector(".meta").textContent = meta;
  $("#chat").appendChild(row);

  if (saveHistory && (role === "user" || role === "assistant")) {
    saveLocalMessage(role, text, meta, sources);
  }
  scrollChat();
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
}

function saveHistory() {
  localStorage.setItem("nutriai_chat_history", JSON.stringify(chatHistory.slice(0, 30)));
}

function createLocalChat(title = "Cuộc trò chuyện mới") {
  const item = {
    id: crypto.randomUUID(),
    title,
    createdAt: Date.now(),
    backendId: null,
    messages: []
  };
  chatHistory.unshift(item);
  currentLocalChatId = item.id;
  saveHistory();
  renderHistory();
  return item;
}

function getCurrentLocalChat() {
  return chatHistory.find((item) => item.id === currentLocalChatId);
}

function saveLocalMessage(role, text, meta, sources) {
  if (!currentLocalChatId) createLocalChat();
  const item = getCurrentLocalChat();
  if (!item) return;
  if (role === "user" && item.messages.length === 0) {
    item.title = text.length > 42 ? `${text.slice(0, 42)}…` : text;
  }
  item.messages.push({ role, text, meta, sources, at: Date.now() });
  item.createdAt = Date.now();
  chatHistory = [item, ...chatHistory.filter((x) => x.id !== item.id)];
  saveHistory();
  renderHistory();
}

function renderHistory(filter = "") {
  const container = $("#chatHistory");
  if (!container) return;
  const query = filter.trim().toLowerCase();
  const items = chatHistory.filter((item) => !query || item.title.toLowerCase().includes(query));
  if (!items.length) {
    container.innerHTML = `<div class="history-empty">${query ? "Không tìm thấy cuộc trò chuyện" : "Chưa có cuộc trò chuyện nào"}</div>`;
    return;
  }
  container.innerHTML = items.map((item) => `
    <button class="history-item ${item.id === currentLocalChatId ? "active" : ""}" data-history-id="${item.id}" title="${escapeHtml(item.title)}">
      <span class="history-icon">◌</span>
      <span class="history-title">${escapeHtml(item.title)}</span>
      <span class="history-date">${formatHistoryDate(item.createdAt)}</span>
    </button>
  `).join("");
  container.querySelectorAll("[data-history-id]").forEach((button) => {
    button.addEventListener("click", () => openLocalChat(button.dataset.historyId));
  });
}

function formatHistoryDate(timestamp) {
  const diff = Date.now() - timestamp;
  if (diff < 86400000) return "Hôm nay";
  if (diff < 172800000) return "Hôm qua";
  return new Date(timestamp).toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" });
}

function openLocalChat(id) {
  const item = chatHistory.find((x) => x.id === id);
  if (!item) return;
  currentLocalChatId = id;
  conversationId = item.backendId || null;
  $("#chat").innerHTML = "";
  if (!item.messages.length) {
    $("#chat").innerHTML = `<div id="welcome" class="welcome">
      <div class="hero-orb"><div class="orb-inner">✦</div></div>
      <div class="welcome-kicker">NUTRIAI DEMO</div>
      <h2>Xin chào, mình là NutriAI.</h2>
      <p>Bạn có thể tiếp tục cuộc trò chuyện này bằng cách đặt câu hỏi bên dưới.</p>
    </div>`;
  } else {
    item.messages.forEach((m) => addMessage(m.role, m.text, m.meta, m.sources, false));
  }
  renderHistory();
  scrollChat();
}

function startNewChat() {
  conversationId = null;
  currentLocalChatId = null;
  $("#chat").innerHTML = `<div id="welcome" class="welcome">
    <div class="hero-orb"><div class="orb-inner">✦</div></div>
    <div class="welcome-kicker">NUTRIAI DEMO</div>
    <h2>Xin chào, mình là NutriAI.</h2>
    <p>Đặt câu hỏi về dinh dưỡng, cân nặng, bữa ăn, tập luyện và lối sống lành mạnh.</p>
  </div>`;
  $("#message").focus();
  renderHistory();
}

function openProfile() {
  $("#pName").value = profile.name || "";
  $("#pAge").value = profile.age || "";
  $("#pGender").value = profile.gender || "";
  $("#pHeight").value = profile.height || "";
  $("#pWeight").value = profile.weight || "";
  $("#pGoal").value = profile.goal || "";
  $("#pActivity").value = profile.activity_level || "moderate";
  $("#profileModal").classList.remove("hidden");
}

function openKnowledge() {
  $("#knowledgeModal").classList.remove("hidden");
  loadKnowledge();
}

function closeModals() {
  document.querySelectorAll(".modal").forEach((modal) => modal.classList.add("hidden"));
}

async function loadKnowledge() {
  try {
    const response = await fetch(`${API_BASE}/api/knowledge`);
    const data = await response.json();
    $("#kDocs").textContent = data.documents ?? "—";
    $("#kChunks").textContent = data.chunks ?? "—";
    $("#kMode").textContent = `${data.mode || "TXT retrieval"} · đã nạp`;
    $("#ragStatus").textContent = `RAG · ${data.chunks || 0} đoạn TXT`;
  } catch {
    $("#ragStatus").textContent = "RAG · chưa kết nối";
  }
}

async function health() {
  try {
    const data = await (await fetch(`${API_BASE}/health`)).json();
    $("#dbStatus").textContent = data.database ? "Database · Supabase" : "Database · local demo";
    $("#ragStatus").textContent = `RAG · ${data.knowledge?.chunks || 0} đoạn TXT`;
  } catch {
    $("#dbStatus").textContent = "Backend · chưa chạy";
    $("#ragStatus").textContent = "RAG · chưa kết nối";
  }
}

async function ensureConversation() {
  if (conversationId) return;
  const response = await fetch(`${API_BASE}/api/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, title: "NutriAI" }),
  });
  if (!response.ok) throw new Error("Không tạo được phiên chat");
  conversationId = (await response.json()).id;
  const current = getCurrentLocalChat();
  if (current) {
    current.backendId = conversationId;
    saveHistory();
  }
}

async function send(text) {
  text = text.trim();
  if (!text) return;
  if (!currentLocalChatId) {
    createLocalChat(text.length > 42 ? `${text.slice(0, 42)}…` : text);
  }
  addMessage("user", text, "Bạn");
  $("#message").value = "";
  autoResize();

  const typing = document.createElement("div");
  typing.id = "typing";
  typing.className = "message assistant";
  typing.innerHTML = `<div><div class="bubble"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span> NutriAI đang truy hồi kiến thức...</div><div class="meta">RAG · TXT retrieval</div></div>`;
  $("#chat").appendChild(typing);
  scrollChat();

  try {
    await ensureConversation();
    const response = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, conversation_id: conversationId, message: text, profile }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Backend lỗi");
    typing.remove();
    addMessage("assistant", data.answer, `NutriAI · ${data.model || "RAG TXT"}`, data.sources || []);
  } catch (error) {
    typing.remove();
    addMessage("assistant", `Chưa thể trả lời: ${error.message}`, "Hệ thống");
  }
}

function autoResize() {
  const field = $("#message");
  field.style.height = "auto";
  field.style.height = `${Math.min(field.scrollHeight, 130)}px`;
}

$("#chatForm").addEventListener("submit", (event) => {
  event.preventDefault();
  send($("#message").value);
});
$("#message").addEventListener("input", autoResize);
$("#message").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    send(event.target.value);
  }
});
document.querySelectorAll("[data-q]").forEach((button) => button.addEventListener("click", () => send(button.dataset.q)));

$("#profileBtn").addEventListener("click", openProfile);
$("#profileNav").addEventListener("click", openProfile);
$("#knowledgeNav").addEventListener("click", openKnowledge);
$("#chatNav").addEventListener("click", () => $("#message").focus());
document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", closeModals));
$("#newChat").addEventListener("click", startNewChat);
$("#clearChatNav").addEventListener("click", startNewChat);
$("#focusChatNav").addEventListener("click", () => $("#message").focus());
$("#chatSearch").addEventListener("input", (event) => renderHistory(event.target.value));
$("#clearHistory").addEventListener("click", () => {
  if (!chatHistory.length) return;
  if (confirm("Xóa toàn bộ lịch sử cuộc trò chuyện trên thiết bị này?")) {
    chatHistory = [];
    currentLocalChatId = null;
    conversationId = null;
    saveHistory();
    renderHistory();
    startNewChat();
    toast("Đã xóa lịch sử trên máy");
  }
});
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    $("#chatSearch").focus();
  }
});
$("#reloadKnowledge").addEventListener("click", async () => {
  try {
    await fetch(`${API_BASE}/api/knowledge/reload`, { method: "POST" });
    await loadKnowledge();
    toast("Đã nạp lại knowledge.txt");
  } catch {
    toast("Không thể nạp lại kho kiến thức");
  }
});

$("#profileForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  profile = {
    user_id: userId,
    name: $("#pName").value.trim(),
    age: Number($("#pAge").value) || null,
    gender: $("#pGender").value || null,
    height: Number($("#pHeight").value) || null,
    weight: Number($("#pWeight").value) || null,
    goal: $("#pGoal").value || null,
    activity_level: $("#pActivity").value || "moderate",
  };
  localStorage.setItem("nutriai_profile", JSON.stringify(profile));
  try {
    await fetch(`${API_BASE}/api/profile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    });
    toast("Đã lưu hồ sơ");
  } catch {
    toast("Đã lưu hồ sơ trên máy");
  }
  closeModals();
});

renderHistory();
health();
loadKnowledge();
