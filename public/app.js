
const API_BASE = window.location.origin;
const $ = (selector) => document.querySelector(selector);

// Supabase Project URL phải là URL gốc, không thêm /rest/v1/
const SUPABASE_URL = "https://schqocxepqucmkxepqhj.supabase.co";
const SUPABASE_PUBLISHABLE_KEY =
  "sb_publishable_dnvBL7ufxmdny8GzDMvO5g_pFR2q0XY";

const supabaseClient = window.supabase?.createClient
  ? window.supabase.createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)
  : null;

let authSession = null;
let authUser = null;
let authMode = "login";

let profile = JSON.parse(localStorage.getItem("nutriai_profile") || "{}");
let userId = localStorage.getItem("nutriai_user_id") || crypto.randomUUID();
let conversationId = null;
let currentLocalChatId = null;
let chatHistory = JSON.parse(localStorage.getItem("nutriai_chat_history") || "[]");

localStorage.setItem("nutriai_user_id", userId);

// =====================================================
// THÔNG BÁO
// =====================================================

function toast(message) {
  const el = $("#toast");
  if (!el) return;

  el.textContent = message;
  el.style.display = "block";

  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => {
    el.style.display = "none";
  }, 3000);
}

function scrollChat() {
  const chat = $("#chat");
  if (chat) chat.scrollTop = chat.scrollHeight;
}

function closeModals() {
  document.querySelectorAll(".modal").forEach((modal) => {
    modal.classList.add("hidden");
  });
}

// =====================================================
// SUPABASE AUTH VÀ TOKEN
// =====================================================

async function getAuthHeaders(extraHeaders = {}) {
  const headers = { ...extraHeaders };

  if (!supabaseClient) {
    return headers;
  }

  const { data, error } = await supabaseClient.auth.getSession();

  if (error) throw error;

  authSession = data.session;
  authUser = data.session?.user || null;

  if (authSession?.access_token) {
    headers.Authorization = `Bearer ${authSession.access_token}`;
  }

  return headers;
}

function updateAuthUI() {
  const button = $("#authBtn");
  const title = $("#authTitle");
  const description = $("#authDescription");
  const form = $("#authForm");
  const panel = $("#signedInPanel");
  const email = $("#authUserEmail");

  if (button) {
    button.textContent = authUser ? "Tài khoản" : "Đăng nhập";
  }

  if (authUser) {
    if (title) title.textContent = "Tài khoản của bạn";

    if (description) {
      description.textContent =
        "Bạn đã đăng nhập vào NutriAI.";
    }

    if (form) form.classList.add("hidden");
    if (panel) panel.classList.remove("hidden");
    if (email) email.textContent = authUser.email || "";
  } else {
    if (title) {
      title.textContent =
        authMode === "signup" ? "Tạo tài khoản" : "Đăng nhập";
    }

    if (description) {
      description.textContent =
        "Đăng nhập để đồng bộ lịch sử trò chuyện và hồ sơ sức khỏe.";
    }

    if (form) form.classList.remove("hidden");
    if (panel) panel.classList.add("hidden");
  }
}

function openAuth() {
  if (!supabaseClient) {
    toast("Không tải được Supabase. Hãy kiểm tra kết nối mạng.");
    return;
  }

  updateAuthUI();

  const message = $("#authMessage");
  if (message) message.textContent = "";

  $("#authModal")?.classList.remove("hidden");
}

$("#authBtn")?.addEventListener("click", openAuth);

$("#authSwitch")?.addEventListener("click", () => {
  authMode = authMode === "login" ? "signup" : "login";

  $("#authTitle").textContent =
    authMode === "signup" ? "Tạo tài khoản" : "Đăng nhập";

  $("#authSubmit").textContent =
    authMode === "signup" ? "Đăng ký" : "Đăng nhập";

  $("#authSwitch").textContent =
    authMode === "signup"
      ? "Đã có tài khoản? Đăng nhập"
      : "Tạo tài khoản";

  $("#authPassword").autocomplete =
    authMode === "signup" ? "new-password" : "current-password";

  $("#authMessage").textContent = "";
  updateAuthUI();
});

$("#authForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();

  if (!supabaseClient) {
    toast("Không tải được Supabase.");
    return;
  }

  const email = $("#authEmail").value.trim();
  const password = $("#authPassword").value;
  const submit = $("#authSubmit");
  const message = $("#authMessage");

  submit.disabled = true;
  message.textContent = "Đang xử lý...";

  try {
    let result;

    if (authMode === "signup") {
      result = await supabaseClient.auth.signUp({
        email,
        password,
        options: {
          emailRedirectTo: window.location.origin
        }
      });
    } else {
      result = await supabaseClient.auth.signInWithPassword({
        email,
        password
      });
    }

    if (result.error) throw result.error;

    if (authMode === "signup" && !result.data.session) {
      message.textContent =
        "Đăng ký thành công. Hãy kiểm tra email để xác nhận tài khoản, sau đó đăng nhập.";
      return;
    }

    authSession = result.data.session;
    authUser = result.data.user;

    // Không tái sử dụng ID chat khách cho tài khoản cloud.
    conversationId = null;
    currentLocalChatId = null;

    updateAuthUI();
    closeModals();

    toast(
      authMode === "signup"
        ? "Đăng ký thành công!"
        : "Đăng nhập thành công!"
    );

    await loadCloudProfile();
    await loadCloudHistory();
  } catch (error) {
    message.textContent =
      error.message || "Không thể xác thực tài khoản.";
  } finally {
    submit.disabled = false;
  }
});

$("#authLogout")?.addEventListener("click", async () => {
  if (!supabaseClient) return;

  const { error } = await supabaseClient.auth.signOut();

  if (error) {
    toast("Đăng xuất thất bại: " + error.message);
    return;
  }

  authSession = null;
  authUser = null;
  conversationId = null;
  currentLocalChatId = null;

  updateAuthUI();
  closeModals();
  toast("Đã đăng xuất. Lịch sử trên thiết bị vẫn được giữ.");
  startNewChat();
});

if (supabaseClient) {
  supabaseClient.auth.onAuthStateChange((_event, session) => {
    authSession = session;
    authUser = session?.user || null;
    updateAuthUI();
  });

  supabaseClient.auth.getSession().then(async ({ data, error }) => {
    if (error) {
      console.error("Không đọc được phiên đăng nhập:", error.message);
      return;
    }

    authSession = data.session;
    authUser = data.session?.user || null;
    updateAuthUI();

    if (authUser) {
      try {
        await loadCloudProfile();
        await loadCloudHistory();
      } catch (error) {
        console.error("Lỗi đồng bộ dữ liệu:", error);
      }
    }
  });
} else {
  console.error(
    "Supabase chưa tải được. Hãy kiểm tra thẻ script trong index.html."
  );
}

// =====================================================
// CHAT VÀ LỊCH SỬ TRÊN THIẾT BỊ
// =====================================================

function saveHistory() {
  localStorage.setItem(
    "nutriai_chat_history",
    JSON.stringify(chatHistory.slice(0, 30))
  );
}

function createLocalChat(title = "Cuộc trò chuyện mới") {
  const item = {
    id: crypto.randomUUID(),
    title,
    createdAt: Date.now(),
    backendId: null,
    cloud: false,
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

  item.messages.push({
    role,
    text,
    meta,
    sources,
    at: Date.now()
  });

  item.createdAt = Date.now();

  chatHistory = [
    item,
    ...chatHistory.filter((entry) => entry.id !== item.id)
  ];

  saveHistory();
  renderHistory();
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;"
  }[char]));
}

function formatHistoryDate(timestamp) {
  const diff = Date.now() - timestamp;

  if (diff < 86400000) return "Hôm nay";
  if (diff < 172800000) return "Hôm qua";

  return new Date(timestamp).toLocaleDateString("vi-VN", {
    day: "2-digit",
    month: "2-digit"
  });
}

function renderHistory(filter = "") {
  const container = $("#chatHistory");
  if (!container) return;

  const query = filter.trim().toLowerCase();

  const items = chatHistory.filter((item) =>
    !query || item.title.toLowerCase().includes(query)
  );

  if (!items.length) {
    container.innerHTML = `
      <div class="history-empty">
        ${query ? "Không tìm thấy cuộc trò chuyện" : "Chưa có cuộc trò chuyện nào"}
      </div>`;
    return;
  }

  container.innerHTML = items.map((item) => `
    <button class="history-item ${item.id === currentLocalChatId ? "active" : ""}"
      data-history-id="${escapeHtml(item.id)}"
      title="${escapeHtml(item.title)}">
      <span class="history-icon">◌</span>
      <span class="history-title">${escapeHtml(item.title)}</span>
      <span class="history-date">${formatHistoryDate(item.createdAt)}</span>
    </button>
  `).join("");

  container.querySelectorAll("[data-history-id]").forEach((button) => {
    button.addEventListener("click", () => {
      openLocalChat(button.dataset.historyId);
    });
  });
}

function addMessage(role, text, meta = "", sources = [], saveHistoryLocally = true) {
  $("#welcome")?.remove();

  const row = document.createElement("div");
  row.className = `message ${role}`;

  const sourceHtml = sources.length
    ? `<div class="sources">${sources.map((source) =>
        `<span class="source-chip">Nguồn: ${escapeHtml(source.title || source)}</span>`
      ).join("")}</div>`
    : "";

  row.innerHTML = `
    <div>
      <div class="bubble"></div>
      ${sourceHtml}
      <div class="meta"></div>
    </div>`;

  row.querySelector(".bubble").textContent = text;
  row.querySelector(".meta").textContent = meta;
  $("#chat").appendChild(row);

  if (
    saveHistoryLocally &&
    (role === "user" || role === "assistant")
  ) {
    saveLocalMessage(role, text, meta, sources);
  }

  scrollChat();
}

function openLocalChat(id) {
  const item = chatHistory.find((entry) => entry.id === id);
  if (!item) return;

  currentLocalChatId = id;
  conversationId = item.cloud ? item.backendId : null;

  $("#chat").innerHTML = "";

  if (!item.messages.length) {
    $("#chat").innerHTML = `
      <div id="welcome" class="welcome">
        <div class="hero-orb"><div class="orb-inner">✦</div></div>
        <div class="welcome-kicker">NUTRIAI DEMO</div>
        <h2>Xin chào, mình là NutriAI.</h2>
        <p>Bạn có thể tiếp tục cuộc trò chuyện này bằng cách đặt câu hỏi bên dưới.</p>
      </div>`;
  } else {
    item.messages.forEach((message) => {
      addMessage(
        message.role,
        message.text,
        message.meta,
        message.sources || [],
        false
      );
    });
  }

  renderHistory();
  scrollChat();
}

function startNewChat() {
  conversationId = null;
  currentLocalChatId = null;

  $("#chat").innerHTML = `
    <div id="welcome" class="welcome">
      <div class="hero-orb"><div class="orb-inner">✦</div></div>
      <div class="welcome-kicker">NUTRIAI DEMO</div>
      <h2>Xin chào, mình là NutriAI.</h2>
      <p>Đặt câu hỏi về dinh dưỡng, cân nặng, bữa ăn, tập luyện và lối sống lành mạnh.</p>
    </div>`;

  $("#message").focus();
  renderHistory();
}

// =====================================================
// ĐỒNG BỘ LỊCH SỬ CHAT VỚI BACKEND
// =====================================================

async function loadCloudHistory() {
  if (!authUser) return;

  const response = await fetch(`${API_BASE}/api/conversations`, {
    headers: await getAuthHeaders()
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Không tải được lịch sử trên cloud.");
  }

  const cloudItems = data.items || [];

  for (const conversation of cloudItems) {
    const backendId = conversation.id;
    if (!backendId) continue;

    const existing = chatHistory.find(
      (item) => item.cloud && item.backendId === backendId
    );

    if (existing) continue;

    const messagesResponse = await fetch(
      `${API_BASE}/api/conversations/${encodeURIComponent(backendId)}/messages`,
      { headers: await getAuthHeaders() }
    );

    if (!messagesResponse.ok) continue;

    const messagesData = await messagesResponse.json();

    const messages = (messagesData.items || []).map((message) => ({
      role: message.role,
      text: message.content || "",
      meta: message.role === "user" ? "Bạn" : "NutriAI",
      sources: [],
      at: message.created_at
        ? new Date(message.created_at).getTime()
        : Date.now()
    }));

    chatHistory.push({
      id: `cloud-${backendId}`,
      backendId,
      cloud: true,
      title: conversation.title || "Cuộc trò chuyện",
      createdAt: conversation.created_at
        ? new Date(conversation.created_at).getTime()
        : Date.now(),
      messages
    });
  }

  saveHistory();
  renderHistory();
}

// =====================================================
// HỒ SƠ SỨC KHỎE
// =====================================================

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

async function loadCloudProfile() {
  if (!authUser) return;

  const response = await fetch(`${API_BASE}/api/profile`, {
    headers: await getAuthHeaders()
  });

  if (!response.ok) {
    if (response.status === 404) return;
    throw new Error("Không tải được hồ sơ từ cloud.");
  }

  const data = await response.json();

  if (data.profile) {
    profile = { ...profile, ...data.profile };
    localStorage.setItem("nutriai_profile", JSON.stringify(profile));
  }
}

$("#profileForm").addEventListener("submit", async (event) => {
  event.preventDefault();

  profile = {
    name: $("#pName").value.trim(),
    age: Number($("#pAge").value) || null,
    gender: $("#pGender").value || null,
    height: Number($("#pHeight").value) || null,
    weight: Number($("#pWeight").value) || null,
    goal: $("#pGoal").value || null,
    activity_level: $("#pActivity").value || "moderate"
  };

  localStorage.setItem("nutriai_profile", JSON.stringify(profile));

  if (!authUser) {
    toast("Đã lưu trên máy. Đăng nhập để đồng bộ lên cloud.");
    closeModals();
    return;
  }

  try {
    const response = await fetch(`${API_BASE}/api/profile`, {
      method: "PUT",
      headers: await getAuthHeaders({
        "Content-Type": "application/json"
      }),
      body: JSON.stringify(profile)
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Không thể lưu hồ sơ.");
    }

    toast("Đã lưu hồ sơ lên Supabase.");
    closeModals();
  } catch (error) {
    toast(error.message || "Không thể lưu hồ sơ lên cloud.");
  }
});

// =====================================================
// KHO KIẾN THỨC VÀ TRẠNG THÁI BACKEND
// =====================================================

function openKnowledge() {
  $("#knowledgeModal").classList.remove("hidden");
  loadKnowledge();
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
    const response = await fetch(`${API_BASE}/api/health`);
    if (!response.ok) throw new Error("Health check thất bại");

    const data = await response.json();

    $("#dbStatus").textContent = data.database
      ? "Database · Supabase"
      : "Database · local demo";

    $("#ragStatus").textContent =
      `RAG · ${data.knowledge?.chunks || 0} đoạn TXT`;
  } catch {
    $("#dbStatus").textContent = "Backend · chưa chạy";
    $("#ragStatus").textContent = "RAG · chưa kết nối";
  }
}

// =====================================================
// GỬI TIN NHẮN
// =====================================================

async function ensureConversation() {
  // Khách không tạo cuộc trò chuyện trên cloud.
  if (!authUser) {
    conversationId = null;
    return;
  }

  const current = getCurrentLocalChat();

  if (
    conversationId &&
    current?.cloud &&
    current.backendId === conversationId
  ) {
    return;
  }

  // Không tái sử dụng ID của cuộc trò chuyện khách.
  const response = await fetch(`${API_BASE}/api/conversations`, {
    method: "POST",
    headers: await getAuthHeaders({
      "Content-Type": "application/json"
    }),
    body: JSON.stringify({
      title: current?.title || "Cuộc trò chuyện mới"
    })
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Không tạo được phiên chat.");
  }

  conversationId = data.id;

  if (current && data.guest_mode !== true) {
    current.backendId = conversationId;
    current.cloud = true;
    saveHistory();
  }
}

async function send(text) {
  text = text.trim();
  if (!text) return;

  if (!currentLocalChatId) {
    createLocalChat(
      text.length > 42 ? `${text.slice(0, 42)}…` : text
    );
  }

  addMessage("user", text, "Bạn");

  $("#message").value = "";
  autoResize();

  const typing = document.createElement("div");
  typing.id = "typing";
  typing.className = "message assistant";
  typing.innerHTML = `
    <div>
      <div class="bubble">
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
        NutriAI đang truy hồi kiến thức...
      </div>
      <div class="meta">RAG · TXT retrieval</div>
    </div>`;

  $("#chat").appendChild(typing);
  scrollChat();

  try {
    await ensureConversation();

    const response = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: await getAuthHeaders({
        "Content-Type": "application/json"
      }),
      body: JSON.stringify({
        conversation_id: authUser ? conversationId : null,
        message: text,
        profile
      })
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Backend lỗi.");
    }

    typing.remove();

    addMessage(
      "assistant",
      data.answer,
      `NutriAI · ${data.model || "RAG TXT"}`,
      data.sources || []
    );
  } catch (error) {
    typing.remove();
    addMessage(
      "assistant",
      `Chưa thể trả lời: ${error.message}`,
      "Hệ thống"
    );
  }
}

// =====================================================
// SỰ KIỆN GIAO DIỆN
// =====================================================

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

document.querySelectorAll("[data-q]").forEach((button) => {
  button.addEventListener("click", () => send(button.dataset.q));
});

$("#profileBtn").addEventListener("click", openProfile);
$("#profileNav").addEventListener("click", openProfile);
$("#knowledgeNav").addEventListener("click", openKnowledge);
$("#chatNav").addEventListener("click", () => $("#message").focus());

document.querySelectorAll("[data-close]").forEach((button) => {
  button.addEventListener("click", closeModals);
});

$("#newChat").addEventListener("click", startNewChat);
$("#clearChatNav").addEventListener("click", startNewChat);
$("#focusChatNav").addEventListener("click", () => $("#message").focus());

$("#chatSearch").addEventListener("input", (event) => {
  renderHistory(event.target.value);
});

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
  if (
    (event.ctrlKey || event.metaKey) &&
    event.key.toLowerCase() === "k"
  ) {
    event.preventDefault();
    $("#chatSearch").focus();
  }
});

$("#reloadKnowledge").addEventListener("click", async () => {
  try {
    const response = await fetch(`${API_BASE}/api/knowledge/reload`, {
      method: "POST"
    });

    if (!response.ok) throw new Error("Không thể nạp lại kho kiến thức.");

    await loadKnowledge();
    toast("Đã nạp lại knowledge.txt");
  } catch {
    toast("Không thể nạp lại kho kiến thức");
  }
});

// =====================================================
// KHỞI TẠO
// =====================================================

renderHistory();
updateAuthUI();
health();
loadKnowledge();
