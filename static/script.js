/**
 * Linux Laptop Hardware Q&A Assistant - Frontend Client
 * Handles live REST communication, telemetry hydration, theme switching,
 * and conversational multi-turn messaging.
 */

// Application State
const state = {
  sessionId: localStorage.getItem("hardware_assistant_session") || generateUUID(),
  theme: localStorage.getItem("hardware_assistant_theme") || "dark",
  isGenerating: false,
};

// Persist session ID
localStorage.setItem("hardware_assistant_session", state.sessionId);

// DOM Elements
const dom = {
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  sendBtn: document.getElementById("send-btn"),
  messagesContainer: document.getElementById("messages-container"),
  suggestionChips: document.getElementById("suggestion-chips"),
  themeToggle: document.getElementById("theme-toggle"),
  themeIcon: document.getElementById("theme-icon"),
  clearChatBtn: document.getElementById("clear-chat-btn"),
  refreshHwBtn: document.getElementById("refresh-hw-btn"),
  sidebar: document.getElementById("sidebar"),
  sidebarToggle: document.getElementById("sidebar-toggle"),
  
  // Hardware Cards
  cardCpuVal: document.getElementById("card-cpu-val"),
  cardCpuSub: document.getElementById("card-cpu-sub"),
  cardMemVal: document.getElementById("card-mem-val"),
  cardMemSub: document.getElementById("card-mem-sub"),
  cardStorageVal: document.getElementById("card-storage-val"),
  cardStorageSub: document.getElementById("card-storage-sub"),
  cardGpuVal: document.getElementById("card-gpu-val"),
  cardGpuSub: document.getElementById("card-gpu-sub"),
  cardOsVal: document.getElementById("card-os-val"),
  cardOsSub: document.getElementById("card-os-sub"),
  
  // Status Indicators
  platformIndicator: document.getElementById("platform-indicator"),
  platformStatus: document.getElementById("platform-status"),
  aiIndicator: document.getElementById("ai-indicator"),
  aiStatus: document.getElementById("ai-status"),
};

// ==================== INITIALIZATION ====================
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  setupEventListeners();
  fetchHealthStatus();
  fetchHardwareOverview();
});

function generateUUID() {
  return "sess-" + Math.random().toString(36).substring(2, 9) + Date.now().toString(36);
}

// ==================== THEME MANAGEMENT ====================
function initTheme() {
  document.documentElement.setAttribute("data-theme", state.theme);
  updateThemeIcon();
}

function toggleTheme() {
  state.theme = state.theme === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", state.theme);
  localStorage.setItem("hardware_assistant_theme", state.theme);
  updateThemeIcon();
}

function updateThemeIcon() {
  if (state.theme === "dark") {
    dom.themeIcon.innerHTML = `<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>`;
  } else {
    dom.themeIcon.innerHTML = `<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>`;
  }
}

// ==================== EVENT LISTENERS ====================
function setupEventListeners() {
  dom.themeToggle.addEventListener("click", toggleTheme);
  
  if (dom.sidebarToggle) {
    dom.sidebarToggle.addEventListener("click", () => {
      dom.sidebar.classList.toggle("open");
    });
  }

  dom.refreshHwBtn.addEventListener("click", () => {
    fetchHardwareOverview();
    fetchHealthStatus();
  });

  dom.clearChatBtn.addEventListener("click", clearConversation);

  // Auto-resize chat input
  dom.chatInput.addEventListener("input", function () {
    this.style.height = "auto";
    this.style.height = Math.min(this.scrollHeight, 120) + "px";
  });

  // Enter sends, Shift+Enter new line
  dom.chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      dom.chatForm.dispatchEvent(new Event("submit"));
    }
  });

  dom.chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = dom.chatInput.value.trim();
    if (text && !state.isGenerating) {
      sendMessage(text);
    }
  });
}

// ==================== TELEMETRY FETCHERS ====================
async function fetchHealthStatus() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) return;
    const data = await res.json();
    
    // Update platform indicator
    dom.platformIndicator.classList.add("online");
    dom.platformStatus.textContent = data.is_linux
      ? `System: Linux (${data.platform.split(" ")[0]})`
      : `System: ${data.platform.split(" ")[0]} (Fallback)`;

    // Update Ollama indicator
    if (data.ollama_available) {
      dom.aiIndicator.classList.add("online");
      dom.aiStatus.textContent = `AI: Ollama (${data.ollama_model || "Local"})`;
    } else {
      dom.aiIndicator.classList.remove("online");
      dom.aiStatus.textContent = "AI: Rule-based Synthesizer";
    }
  } catch (err) {
    console.warn("Health check error:", err);
  }
}

async function fetchHardwareOverview() {
  try {
    const res = await fetch("/api/hardware");
    if (!res.ok) return;
    const data = await res.json();

    // CPU Card
    const cpu = data.cpu;
    dom.cardCpuVal.textContent = cpu.model || "Unknown Processor";
    const coresText = cpu.physical_cores
      ? `${cpu.physical_cores} Cores / ${cpu.logical_threads} Threads`
      : `${cpu.logical_threads || "?"} Threads`;
    dom.cardCpuSub.textContent = `${coresText} (${cpu.architecture})`;

    // Memory Card
    const mem = data.memory;
    dom.cardMemVal.textContent = `${mem.total_formatted} RAM`;
    dom.cardMemSub.textContent = `${mem.available_formatted} available (${mem.percent_used}% used)`;

    // Storage Card
    const storage = data.storage;
    dom.cardStorageVal.textContent = storage.total_capacity_formatted || "Storage";
    const nvmeText = storage.nvme_count > 0 ? `${storage.nvme_count} NVMe SSD` : "SATA / Disk";
    dom.cardStorageSub.textContent = `${storage.devices.length} drives (${nvmeText})`;

    // GPU Card
    const gpu = data.gpu;
    if (gpu.devices && gpu.devices.length > 0) {
      dom.cardGpuVal.textContent = gpu.devices[0].name.split("(")[0].trim();
      dom.cardGpuSub.textContent = `${gpu.devices.length} Adapter(s) [${gpu.devices[0].vendor}]`;
    } else {
      dom.cardGpuVal.textContent = "Integrated Graphics";
      dom.cardGpuSub.textContent = "No dedicated GPU detected";
    }

    // OS Card
    const os = data.os;
    dom.cardOsVal.textContent = `${os.distro_name} ${os.distro_version}`.trim();
    dom.cardOsSub.textContent = `Kernel ${os.kernel_version}`;
  } catch (err) {
    console.error("Hardware overview fetch failure:", err);
  }
}

// ==================== CHAT ACTIONS ====================
function askPreset(question) {
  if (state.isGenerating) return;
  dom.chatInput.value = question;
  sendMessage(question);
  
  // Close sidebar on mobile
  if (window.innerWidth <= 768) {
    dom.sidebar.classList.remove("open");
  }
}

async function sendMessage(question) {
  state.isGenerating = true;
  dom.sendBtn.disabled = true;
  dom.chatInput.value = "";
  dom.chatInput.style.height = "auto";

  // Append user message bubble
  appendUserMessage(question);

  // Append typing indicator
  const typingElem = appendTypingIndicator();
  scrollToBottom();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: question,
        session_id: state.sessionId,
      }),
    });

    typingElem.remove();

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      appendAssistantMessage(
        `Error: ${errData.detail || "Unable to complete hardware inspection."}`,
        "error",
        "system"
      );
      return;
    }

    const data = await res.json();
    appendAssistantMessage(data.answer, data.category, data.source);
    
    // Update suggested questions if provided
    if (data.suggested_questions && data.suggested_questions.length > 0) {
      renderSuggestionChips(data.suggested_questions);
    }
  } catch (err) {
    typingElem.remove();
    appendAssistantMessage(
      "Communication error: Could not reach the assistant server.",
      "error",
      "network"
    );
  } finally {
    state.isGenerating = false;
    dom.sendBtn.disabled = false;
    dom.chatInput.focus();
    scrollToBottom();
  }
}

async function clearConversation() {
  if (!confirm("Clear conversation history and reset session context?")) return;
  
  try {
    await fetch("/api/chat/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId }),
    });
  } catch (e) {
    console.warn("Clear session error:", e);
  }

  state.sessionId = generateUUID();
  localStorage.setItem("hardware_assistant_session", state.sessionId);

  // Clear messages except initial welcome
  dom.messagesContainer.innerHTML = `
    <div class="message assistant-message">
      <div class="message-avatar">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon>
        </svg>
      </div>
      <div class="message-content">
        <div class="message-bubble">
          <p>Conversation cleared. Ready for your hardware questions!</p>
        </div>
        <div class="message-meta">
          <span class="meta-tag">Session Reset</span>
        </div>
      </div>
    </div>
  `;
}

// ==================== MESSAGE RENDERING ====================
function appendUserMessage(text) {
  const msgElem = document.createElement("div");
  msgElem.className = "message user-message";
  msgElem.innerHTML = `
    <div class="message-avatar">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
        <circle cx="12" cy="7" r="4"></circle>
      </svg>
    </div>
    <div class="message-content">
      <div class="message-bubble">
        <p>${escapeHtml(text)}</p>
      </div>
      <div class="message-meta">
        <span>${formatTime(new Date())}</span>
      </div>
    </div>
  `;
  dom.messagesContainer.appendChild(msgElem);
}

function appendAssistantMessage(text, category = "general", source = "rule_based") {
  const msgElem = document.createElement("div");
  msgElem.className = "message assistant-message";

  const sourceLabel = source === "ollama" ? "Ollama LLM" : "Verified Telemetry";
  const catLabel = category ? category.replace("_", " ").toUpperCase() : "HARDWARE";

  msgElem.innerHTML = `
    <div class="message-avatar">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon>
      </svg>
    </div>
    <div class="message-content">
      <div class="message-bubble">
        ${formatMarkdown(text)}
      </div>
      <div class="message-meta">
        <span class="meta-tag">${catLabel}</span>
        <span>&bull; ${sourceLabel}</span>
        <span>&bull; ${formatTime(new Date())}</span>
        <button class="copy-btn" onclick="copyText(this, \`${escapeJs(text)}\`)">Copy</button>
      </div>
    </div>
  `;
  dom.messagesContainer.appendChild(msgElem);
}

function appendTypingIndicator() {
  const elem = document.createElement("div");
  elem.className = "message assistant-message";
  elem.innerHTML = `
    <div class="message-avatar">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon>
      </svg>
    </div>
    <div class="message-content">
      <div class="message-bubble">
        <div class="typing-dots">
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
        </div>
      </div>
    </div>
  `;
  dom.messagesContainer.appendChild(elem);
  return elem;
}

function renderSuggestionChips(chips) {
  dom.suggestionChips.innerHTML = "";
  chips.forEach((q) => {
    const btn = document.createElement("button");
    btn.className = "chip";
    btn.textContent = q;
    btn.onclick = () => askPreset(q);
    dom.suggestionChips.appendChild(btn);
  });
}

function scrollToBottom() {
  dom.messagesContainer.scrollTop = dom.messagesContainer.scrollHeight;
}

// ==================== UTILITIES ====================
function formatTime(date) {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function escapeJs(str) {
  return str.replace(/`/g, "\\`").replace(/\$/g, "\\$");
}

function copyText(btn, text) {
  navigator.clipboard.writeText(text).then(() => {
    const orig = btn.textContent;
    btn.textContent = "Copied!";
    setTimeout(() => {
      btn.textContent = orig;
    }, 1800);
  });
}

/**
 * Lightweight formatting for bold, backticks, bullet lists, and paragraphs.
 */
function formatMarkdown(text) {
  let safe = escapeHtml(text);

  // Bold **text**
  safe = safe.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");

  // Inline `code`
  safe = safe.replace(/`([^`]+)`/g, "<code>$1</code>");

  // Headers ###
  safe = safe.replace(/^### (.*$)/gim, '<div style="font-weight:700; margin: 6px 0;">$1</div>');

  // Bullet items - item
  safe = safe.replace(/^- (.*$)/gim, '<li style="margin-left: 16px;">$1</li>');

  // Double newlines into paragraphs
  const paragraphs = safe.split(/\n\s*\n/);
  return paragraphs.map((p) => `<p>${p.replace(/\n/g, "<br>")}</p>`).join("");
}
