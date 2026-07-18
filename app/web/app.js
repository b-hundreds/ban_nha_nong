"use strict";

const STORAGE_KEY = "ban-nha-nong-conversations-v2";
const REGION_KEY = "ban-nha-nong-region-v2";

const REGION_META = {
  an_giang: {
    name: "An Giang",
    context: "Lúa và mùa vụ Đồng bằng sông Cửu Long",
    questions: [
      "Lúa bị rầy nâu thì dùng thuốc gì?",
      "Tháng 11 ở An Giang nên xuống giống lúa chưa?",
      "Lúa bị đạo ôn lá cần xử lý thế nào?",
      "Thuốc nào đã bị cấm dùng trên lúa?",
    ],
  },
  dak_lak: {
    name: "Đắk Lắk",
    context: "Cà phê, sầu riêng và mùa vụ Tây Nguyên",
    questions: [
      "Cà phê bị rệp sáp thì dùng thuốc gì?",
      "Sau thu hoạch cà phê cần chăm sóc thế nào?",
      "Sầu riêng bị thán thư cần xử lý ra sao?",
      "Mùa mưa ở Đắk Lắk cần lưu ý gì cho vườn?",
    ],
  },
};

const state = {
  conversations: [],
  activeId: null,
  draftRegion: loadRegion(),
  isBusy: false,
  editingMessageId: null,
};

const speechState = {
  button: null,
  chunks: [],
  index: 0,
  token: 0,
  speaking: false,
  voice: null,
  audio: null,
  audioUrl: null,
};

const els = {};

document.addEventListener("DOMContentLoaded", init);

function init() {
  [
    "chat", "statusLine", "conversationList", "historyCount", "newChatBtn",
    "sidebar", "sidebarOpen", "sidebarClose", "sidebarScrim", "brandHome",
    "conversationTitle", "conversationTitleBtn", "titleEdit", "titleInput",
    "regionMenu", "regionName", "composer", "textInput", "sendTextBtn", "micBtn",
  ].forEach((id) => { els[id] = document.getElementById(id); });
  els.regionBtns = Array.from(document.querySelectorAll("[data-region-btn]"));

  els.newChatBtn.addEventListener("click", startNewConversation);
  els.brandHome.addEventListener("click", (event) => {
    event.preventDefault();
    startNewConversation();
  });
  els.sidebarOpen.addEventListener("click", openSidebar);
  els.sidebarClose.addEventListener("click", closeSidebar);
  els.sidebarScrim.addEventListener("click", closeSidebar);
  els.regionBtns.forEach((button) => button.addEventListener("click", () => setRegion(button.dataset.regionBtn)));
  els.conversationTitleBtn.addEventListener("click", beginTitleEdit);
  els.titleEdit.addEventListener("submit", finishTitleEdit);
  els.titleInput.addEventListener("keydown", (event) => {
    if (event.key === "Escape") cancelTitleEdit();
  });
  els.composer.addEventListener("submit", submitTypedText);
  els.textInput.addEventListener("input", () => {
    autoSizeTextarea(els.textInput);
    updateSendState();
  });
  els.textInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      submitTypedText(event);
    }
  });

  document.addEventListener("click", (event) => {
    if (els.regionMenu.open && !els.regionMenu.contains(event.target)) els.regionMenu.open = false;
    document.querySelectorAll(".history-menu").forEach((menu) => {
      if (!menu.parentElement.contains(event.target)) menu.hidden = true;
    });
  });

  setupMic();
  updateRegionUI();
  renderAll();
  updateSendState();
  registerServiceWorker();
  loadConversationsFromServer();
}

function icon(name, className = "") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  if (className) svg.setAttribute("class", className);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#icon-${name}`);
  svg.appendChild(use);
  return svg;
}

function makeId(prefix) {
  if (window.crypto && crypto.randomUUID) return `${prefix}-${crypto.randomUUID()}`;
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function makeSessionId() { return makeId("session"); }

function loadRegion() {
  const saved = localStorage.getItem(REGION_KEY);
  return REGION_META[saved] ? saved : "an_giang";
}

function repairLoadingMessages(conversations) {
  return conversations
    .filter((item) => item && item.id && Array.isArray(item.messages))
    .map((conversation) => ({
      ...conversation,
      messages: conversation.messages.map((message) => message.status === "loading" ? {
        ...message,
        status: "error",
        error: "Lượt trả lời trước bị gián đoạn.",
      } : message),
    }));
}

// Lịch sử lưu ở server (SQLite, data/history.db) thay vì localStorage — xem app/backend/history.py.
async function loadConversationsFromServer() {
  try {
    const response = await fetch("/api/conversations");
    if (!response.ok) throw new Error("load failed");
    let conversations = await response.json();
    if (!Array.isArray(conversations)) conversations = [];
    if (conversations.length === 0) conversations = await migrateLocalStorageOnce();
    state.conversations = repairLoadingMessages(conversations);
    renderAll();
  } catch (_error) {
    setStatus("Không tải được lịch sử từ máy chủ.");
  }
}

// Chạy đúng 1 lần: đẩy hội thoại cũ còn nằm trong localStorage (bản trước) lên server rồi xoá key.
async function migrateLocalStorageOnce() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    if (!Array.isArray(parsed) || parsed.length === 0) return [];
    const valid = parsed.filter((item) => item && item.id && Array.isArray(item.messages));
    await Promise.all(valid.map((conversation) =>
      fetch(`/api/conversations/${encodeURIComponent(conversation.id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(conversation),
      })
    ));
    localStorage.removeItem(STORAGE_KEY);
    return valid;
  } catch (_error) {
    return [];
  }
}

function saveConversations(conversation) {
  const target = conversation || getActiveConversation();
  if (!target) return;
  fetch(`/api/conversations/${encodeURIComponent(target.id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(target),
  }).catch(() => {
    setStatus("Không lưu được lịch sử lên máy chủ.");
  });
}

function getActiveConversation() {
  return state.conversations.find((conversation) => conversation.id === state.activeId) || null;
}

function createConversation() {
  const now = new Date().toISOString();
  const conversation = {
    id: makeId("chat"),
    sessionId: makeSessionId(),
    title: "Cuộc trò chuyện mới",
    titleEdited: false,
    region: state.draftRegion,
    createdAt: now,
    updatedAt: now,
    messages: [],
  };
  state.conversations.unshift(conversation);
  state.activeId = conversation.id;
  return conversation;
}

function ensureConversation() {
  return getActiveConversation() || createConversation();
}

function startNewConversation() {
  const active = getActiveConversation();
  if (active) state.draftRegion = active.region;
  state.activeId = null;
  state.editingMessageId = null;
  cancelTitleEdit();
  closeSidebar();
  updateRegionUI();
  renderAll();
  els.textInput.focus();
}

function openConversation(id) {
  if (!state.conversations.some((conversation) => conversation.id === id)) return;
  state.activeId = id;
  state.editingMessageId = null;
  const conversation = getActiveConversation();
  state.draftRegion = conversation.region;
  localStorage.setItem(REGION_KEY, state.draftRegion);
  closeSidebar();
  updateRegionUI();
  renderAll();
  scrollToBottom(false);
}

function deleteConversation(id) {
  const conversation = state.conversations.find((item) => item.id === id);
  if (!conversation) return;
  if (!window.confirm(`Xoá cuộc trò chuyện “${conversation.title}”?`)) return;
  state.conversations = state.conversations.filter((item) => item.id !== id);
  if (state.activeId === id) state.activeId = null;
  fetch(`/api/conversations/${encodeURIComponent(id)}`, { method: "DELETE" }).catch(() => {
    setStatus("Không xoá được trên máy chủ — lịch sử có thể hiện lại khi tải trang.");
  });
  renderAll();
}

function renameConversation(id) {
  if (state.activeId !== id) openConversation(id);
  beginTitleEdit();
}

function beginTitleEdit() {
  const conversation = getActiveConversation();
  if (!conversation) return;
  els.conversationTitleBtn.hidden = true;
  els.titleEdit.hidden = false;
  els.titleInput.value = conversation.title;
  els.titleInput.focus();
  els.titleInput.select();
}

function finishTitleEdit(event) {
  event.preventDefault();
  const conversation = getActiveConversation();
  if (!conversation) return cancelTitleEdit();
  const title = els.titleInput.value.trim();
  if (title) {
    conversation.title = title.slice(0, 60);
    conversation.titleEdited = true;
    conversation.updatedAt = new Date().toISOString();
    saveConversations(conversation);
  }
  cancelTitleEdit();
  renderHistory();
  updateHeader();
}

function cancelTitleEdit() {
  if (!els.titleEdit) return;
  els.titleEdit.hidden = true;
  els.conversationTitleBtn.hidden = false;
}

function titleFromQuestion(text) {
  const compact = text.replace(/\s+/g, " ").trim();
  if (compact.length <= 42) return compact;
  return `${compact.slice(0, 42).trim()}...`;
}

function setRegion(code) {
  if (!REGION_META[code]) return;
  state.draftRegion = code;
  localStorage.setItem(REGION_KEY, code);
  const conversation = getActiveConversation();
  if (conversation) {
    conversation.region = code;
    conversation.updatedAt = new Date().toISOString();
    saveConversations(conversation);
  }
  els.regionMenu.open = false;
  updateRegionUI();
  if (!conversation || conversation.messages.length === 0) renderChat();
}

function activeRegion() {
  return getActiveConversation()?.region || state.draftRegion;
}

function updateRegionUI() {
  const code = activeRegion();
  const meta = REGION_META[code];
  document.documentElement.dataset.region = code;
  els.regionName.textContent = meta.name;
  els.regionBtns.forEach((button) => {
    const active = button.dataset.regionBtn === code;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-checked", String(active));
  });
}

function renderAll() {
  renderHistory();
  updateHeader();
  renderChat();
}

function updateHeader() {
  const conversation = getActiveConversation();
  els.conversationTitle.textContent = conversation?.title || "Cuộc trò chuyện mới";
  els.conversationTitleBtn.disabled = !conversation;
}

function renderHistory() {
  els.conversationList.replaceChildren();
  els.historyCount.textContent = String(state.conversations.length);
  if (!state.conversations.length) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    empty.textContent = "Chưa có cuộc trò chuyện nào.";
    els.conversationList.appendChild(empty);
    return;
  }

  const ordered = [...state.conversations].sort((a, b) => String(b.updatedAt).localeCompare(String(a.updatedAt)));
  ordered.forEach((conversation) => {
    const item = document.createElement("div");
    item.className = "history-item";
    item.classList.toggle("is-active", conversation.id === state.activeId);

    const main = document.createElement("button");
    main.type = "button";
    main.className = "history-main";
    main.textContent = conversation.title || "Cuộc trò chuyện";
    main.title = conversation.title || "Cuộc trò chuyện";
    main.addEventListener("click", () => openConversation(conversation.id));

    const more = document.createElement("button");
    more.type = "button";
    more.className = "icon-btn history-more";
    more.setAttribute("aria-label", `Tuỳ chọn cho ${conversation.title}`);
    more.appendChild(icon("more"));

    const menu = document.createElement("div");
    menu.className = "history-menu";
    menu.hidden = true;
    menu.appendChild(historyAction("edit", "Đổi tên", () => renameConversation(conversation.id)));
    menu.appendChild(historyAction("trash", "Xoá", () => deleteConversation(conversation.id)));
    more.addEventListener("click", (event) => {
      event.stopPropagation();
      document.querySelectorAll(".history-menu").forEach((other) => {
        if (other !== menu) other.hidden = true;
      });
      menu.hidden = !menu.hidden;
    });

    item.append(main, more, menu);
    els.conversationList.appendChild(item);
  });
}

function historyAction(iconName, label, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.append(icon(iconName), document.createTextNode(label));
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    action();
  });
  return button;
}

function renderChat() {
  stopSpeech();
  els.chat.replaceChildren();
  const conversation = getActiveConversation();
  if (!conversation || conversation.messages.length === 0) {
    renderEmptyState();
    return;
  }

  const thread = document.createElement("div");
  thread.className = "thread";
  conversation.messages.forEach((message) => thread.appendChild(renderExchange(message, conversation)));
  els.chat.appendChild(thread);
}

function renderEmptyState() {
  const meta = REGION_META[activeRegion()];
  const empty = document.createElement("section");
  empty.className = "empty-state";

  const mark = document.createElement("span");
  mark.className = "empty-brand";
  mark.appendChild(icon("leaf"));
  const heading = document.createElement("h1");
  heading.textContent = "Bác đang cần tư vấn điều gì?";
  const copy = document.createElement("p");
  copy.textContent = "Hỏi về cây trồng, sâu bệnh, thuốc bảo vệ thực vật hoặc mùa vụ.";
  const context = document.createElement("span");
  context.className = "empty-region-context";
  context.append(icon("info"), document.createTextNode(`${meta.name}: ${meta.context}`));
  const suggestions = document.createElement("div");
  suggestions.className = "suggestions";
  meta.questions.forEach((question) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "suggestion-btn";
    button.append(document.createTextNode(question), icon("chevron"));
    button.addEventListener("click", () => submitQuestion(question));
    suggestions.appendChild(button);
  });
  empty.append(mark, heading, copy, context, suggestions);
  els.chat.appendChild(empty);
}

function renderExchange(message, conversation) {
  const exchange = document.createElement("article");
  exchange.className = "exchange";
  exchange.dataset.messageId = message.id;
  exchange.appendChild(renderUserMessage(message));
  exchange.appendChild(renderAssistantMessage(message, conversation));
  return exchange;
}

function renderUserMessage(message) {
  const row = document.createElement("div");
  row.className = "user-row";

  if (state.editingMessageId === message.id) {
    row.appendChild(renderEditMessageForm(message));
    return row;
  }

  const bubble = document.createElement("p");
  bubble.className = "user-bubble";
  bubble.textContent = message.text;
  const tools = document.createElement("div");
  tools.className = "message-tools";
  const edit = messageTool("edit", "Sửa", () => {
    state.editingMessageId = message.id;
    renderChat();
    const input = els.chat.querySelector(`[data-message-id="${message.id}"] textarea`);
    if (input) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
  });
  tools.appendChild(edit);

  if (Array.isArray(message.revisions) && message.revisions.length) {
    const history = messageTool("clock", `Đã sửa ${message.revisions.length} lần`, () => {
      const panel = row.querySelector(".revision-panel");
      if (panel) panel.hidden = !panel.hidden;
    });
    tools.appendChild(history);
  }

  row.append(bubble, tools);
  if (Array.isArray(message.revisions) && message.revisions.length) {
    const panel = document.createElement("div");
    panel.className = "revision-panel";
    panel.hidden = true;
    const heading = document.createElement("strong");
    heading.textContent = "Các phiên bản trước";
    panel.appendChild(heading);
    [...message.revisions].reverse().forEach((revision) => {
      const old = document.createElement("p");
      old.textContent = revision.text;
      panel.appendChild(old);
    });
    row.appendChild(panel);
  }
  return row;
}

function messageTool(iconName, label, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "message-tool";
  button.append(icon(iconName), document.createTextNode(label));
  button.addEventListener("click", action);
  return button;
}

function renderEditMessageForm(message) {
  const form = document.createElement("form");
  form.className = "edit-message-form";
  const textarea = document.createElement("textarea");
  textarea.value = message.text;
  textarea.maxLength = 2000;
  textarea.setAttribute("aria-label", "Sửa câu hỏi");
  const actions = document.createElement("div");
  actions.className = "edit-actions";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "small-btn";
  cancel.textContent = "Huỷ";
  cancel.addEventListener("click", () => {
    state.editingMessageId = null;
    renderChat();
  });
  const save = document.createElement("button");
  save.type = "submit";
  save.className = "small-btn primary";
  save.textContent = "Gửi lại";
  actions.append(cancel, save);
  form.append(textarea, actions);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    editQuestion(message.id, textarea.value);
  });
  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Escape") cancel.click();
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  return form;
}

function renderAssistantMessage(message, conversation) {
  const row = document.createElement("div");
  row.className = "assistant-row";
  const label = document.createElement("div");
  label.className = "assistant-label";
  const mark = document.createElement("span");
  mark.className = "assistant-mark";
  mark.appendChild(icon("leaf"));
  label.append(mark, document.createTextNode("Bạn Nhà Nông"));
  row.appendChild(label);

  if (message.status === "loading") {
    const loading = document.createElement("div");
    loading.className = "answer-loading";
    const dots = document.createElement("span");
    dots.className = "loading-dots";
    dots.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
    loading.append(dots, document.createTextNode("Đang tra nguồn phù hợp..."));
    row.appendChild(loading);
    return row;
  }

  if (message.error) {
    const error = document.createElement("div");
    error.className = "error-panel";
    const copy = document.createElement("span");
    copy.textContent = message.error;
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "small-btn";
    retry.textContent = "Gửi lại";
    retry.addEventListener("click", () => retryQuestion(message.id));
    error.append(copy, retry);
    row.appendChild(error);
    return row;
  }

  if (!message.answer) return row;

  const segments = message.answer.answer_segments || [];
  const doseSegments = segments.filter((segment) => segment.type === "dose_block");
  const citationSegments = segments.filter((segment) => segment.type === "citation");
  segments.filter((segment) => segment.type === "text").forEach((segment) => {
    const text = document.createElement("p");
    text.className = "answer-text";
    text.textContent = segment.content;
    row.appendChild(text);
  });

  const answerRegion = message.answer.slots?.region || message.region || conversation.region;
  if (doseSegments.length) row.appendChild(renderDoseList(doseSegments, answerRegion));
  if (citationSegments.length) row.appendChild(renderCitations(citationSegments));
  segments.filter((segment) => segment.type === "abstain").forEach((segment) => {
    row.appendChild(renderHandoff(segment, message.answer, message.text, conversation));
  });
  const speechText = answerSpeechText(message.answer);
  if (speechText) row.appendChild(renderSpeechButton(speechText));
  return row;
}

function speechSupported() {
  return Boolean(
    typeof window !== "undefined" &&
    window.speechSynthesis &&
    typeof window.SpeechSynthesisUtterance === "function"
  );
}

function answerSpeechText(answer) {
  const parts = [];
  const segments = answer?.answer_segments || [];
  segments.forEach((segment) => {
    if (segment.type === "text" && segment.content) {
      parts.push(segment.content);
    } else if (segment.type === "dose_block") {
      if (segment.product) parts.push(`Sản phẩm ${segment.product}.`);
      if (segment.ai) parts.push(`Hoạt chất ${segment.ai}.`);
      const guidance = segment.note || segment.dose_text;
      if (guidance) parts.push(`${guidance}.`);
    } else if (segment.type === "abstain" && segment.reason) {
      parts.push(segment.reason);
    }
  });
  return parts.join(" ").replace(/https?:\/\/\S+/gi, "").replace(/\s+/g, " ").trim();
}

function splitSpeechText(text, maxLength = 240) {
  const sentences = String(text || "").match(/[^.!?…]+[.!?…]+|[^.!?…]+$/g) || [];
  const chunks = [];
  let current = "";

  const pushWords = (sentence) => {
    sentence.trim().split(/\s+/).forEach((word) => {
      if (!word) return;
      if (word.length > maxLength) {
        if (current) { chunks.push(current); current = ""; }
        for (let offset = 0; offset < word.length; offset += maxLength) {
          chunks.push(word.slice(offset, offset + maxLength));
        }
        return;
      }
      const candidate = current ? `${current} ${word}` : word;
      if (candidate.length > maxLength) {
        if (current) chunks.push(current);
        current = word;
      } else {
        current = candidate;
      }
    });
  };

  sentences.forEach((sentence) => {
    const clean = sentence.trim();
    if (!clean) return;
    const candidate = current ? `${current} ${clean}` : clean;
    if (candidate.length <= maxLength) {
      current = candidate;
    } else {
      if (current) { chunks.push(current); current = ""; }
      if (clean.length <= maxLength) current = clean;
      else pushWords(clean);
    }
  });
  if (current) chunks.push(current);
  return chunks;
}

function renderSpeechButton(text) {
  const actions = document.createElement("div");
  actions.className = "answer-actions";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "answer-speech-btn";
  button.setAttribute("aria-label", "Đọc câu trả lời");
  button.setAttribute("aria-pressed", "false");
  setSpeechButtonState(button, false);
  button.addEventListener("click", () => toggleSpeech(button, text));
  actions.appendChild(button);
  return actions;
}

function setSpeechButtonState(button, speaking) {
  if (!button) return;
  button.classList.toggle("is-speaking", speaking);
  button.setAttribute("aria-pressed", String(speaking));
  button.setAttribute("aria-label", speaking ? "Dừng đọc câu trả lời" : "Đọc câu trả lời");
  button.replaceChildren(icon(speaking ? "stop" : "volume"), document.createTextNode(speaking ? "Dừng đọc" : "Đọc câu trả lời"));
}

function preferredVietnameseVoice() {
  const voices = window.speechSynthesis.getVoices();
  return voices.find((voice) => String(voice.lang).toLowerCase() === "vi-vn")
    || voices.find((voice) => String(voice.lang).toLowerCase().startsWith("vi"))
    || null;
}

function waitForVietnameseVoice(timeoutMs = 1600) {
  const available = preferredVietnameseVoice();
  if (available) return Promise.resolve(available);

  return new Promise((resolve) => {
    let finished = false;
    const synth = window.speechSynthesis;
    const finish = () => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      synth.removeEventListener?.("voiceschanged", onVoicesChanged);
      resolve(preferredVietnameseVoice());
    };
    const onVoicesChanged = () => {
      if (preferredVietnameseVoice()) finish();
    };
    const timer = setTimeout(finish, timeoutMs);
    synth.addEventListener?.("voiceschanged", onVoicesChanged);
  });
}

function toggleSpeech(button, text) {
  if (speechState.speaking && speechState.button === button) {
    stopSpeech();
    return;
  }

  stopSpeech();
  speechState.chunks = splitSpeechText(text);
  if (!speechState.chunks.length) return;
  speechState.button = button;
  speechState.index = 0;
  speechState.speaking = true;
  const token = speechState.token;
  setSpeechButtonState(button, true);
  if (!speechSupported()) {
    void playGoogleSpeech(token, text);
    return;
  }
  const availableVoice = preferredVietnameseVoice();
  if (availableVoice) {
    speechState.voice = availableVoice;
    speakNextChunk(token);
    return;
  }

  setStatus("Đang tải giọng đọc tiếng Việt...");
  waitForVietnameseVoice().then((voice) => {
    if (token !== speechState.token || !speechState.speaking) return;
    if (!voice) {
      void playGoogleSpeech(token, text);
      return;
    }
    speechState.voice = voice;
    setStatus("");
    speakNextChunk(token);
  });
}

async function playGoogleSpeech(token, text) {
  if (token !== speechState.token || !speechState.speaking) return;
  setStatus("Thiết bị chưa có giọng Việt, đang tạo giọng đọc Google...");
  try {
    const response = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!response.ok) {
      const body = await safeJson(response);
      throw new Error(body.detail || "Không tạo được giọng đọc Google.");
    }
    const blob = await response.blob();
    if (token !== speechState.token || !speechState.speaking) return;
    if (!blob.size) throw new Error("Máy chủ không trả về âm thanh.");

    const audioUrl = window.URL.createObjectURL(blob);
    const audio = new window.Audio(audioUrl);
    speechState.audio = audio;
    speechState.audioUrl = audioUrl;
    audio.onended = () => {
      if (token === speechState.token) finishSpeech(token);
    };
    audio.onerror = () => {
      if (token !== speechState.token) return;
      finishSpeech(token);
      setStatus("Không phát được file giọng đọc Google.");
    };
    await audio.play();
    if (token === speechState.token) setStatus("");
  } catch (error) {
    if (token !== speechState.token) return;
    finishSpeech(token);
    setStatus(error?.message || "Không tạo được giọng đọc tiếng Việt.");
  }
}

function speakNextChunk(token) {
  if (token !== speechState.token || !speechState.speaking) return;
  if (speechState.index >= speechState.chunks.length) {
    finishSpeech(token);
    return;
  }

  const utterance = new window.SpeechSynthesisUtterance(speechState.chunks[speechState.index]);
  utterance.lang = "vi-VN";
  utterance.rate = 0.95;
  // Không để trình duyệt tự fallback sang giọng tiếng Anh.
  utterance.voice = speechState.voice;
  utterance.onend = () => {
    if (token !== speechState.token) return;
    speechState.index += 1;
    speakNextChunk(token);
  };
  utterance.onerror = (event) => {
    if (token !== speechState.token) return;
    const expectedStop = event.error === "canceled" || event.error === "interrupted";
    finishSpeech(token);
    if (!expectedStop) setStatus("Không thể phát giọng đọc trên trình duyệt này.");
  };
  window.speechSynthesis.speak(utterance);
}

function finishSpeech(token) {
  if (token !== speechState.token) return;
  cleanupGoogleAudio();
  setSpeechButtonState(speechState.button, false);
  speechState.button = null;
  speechState.chunks = [];
  speechState.index = 0;
  speechState.speaking = false;
  speechState.voice = null;
}

function cleanupGoogleAudio() {
  if (speechState.audio) {
    speechState.audio.onended = null;
    speechState.audio.onerror = null;
    speechState.audio.pause();
    speechState.audio.currentTime = 0;
    speechState.audio = null;
  }
  if (speechState.audioUrl) {
    window.URL.revokeObjectURL(speechState.audioUrl);
    speechState.audioUrl = null;
  }
}

function stopSpeech() {
  const oldButton = speechState.button;
  speechState.token += 1;
  if (speechSupported()) window.speechSynthesis.cancel();
  cleanupGoogleAudio();
  speechState.button = null;
  speechState.chunks = [];
  speechState.index = 0;
  speechState.speaking = false;
  speechState.voice = null;
  setSpeechButtonState(oldButton, false);
}

function renderDoseList(segments, region) {
  const list = document.createElement("section");
  list.className = "result-list";
  const head = document.createElement("div");
  head.className = "result-head";
  const count = document.createElement("span");
  count.textContent = `${segments.length} sản phẩm phù hợp`;
  const area = document.createElement("span");
  area.className = "region-result-label";
  area.textContent = REGION_META[region]?.name || "";
  head.append(count, area);
  list.appendChild(head);
  segments.forEach((segment) => {
    const item = document.createElement("div");
    item.className = "dose-row";
    const product = document.createElement("p");
    product.className = "dose-product";
    product.textContent = segment.product;
    const ai = document.createElement("p");
    ai.className = "dose-ai";
    ai.textContent = `Hoạt chất: ${segment.ai}`;
    const note = document.createElement("span");
    note.className = "dose-note";
    note.textContent = segment.note || segment.dose_text;
    item.append(product, ai, note);
    list.appendChild(item);
  });
  return list;
}

function renderCitations(segments) {
  const list = document.createElement("div");
  list.className = "citation-list";
  segments.forEach((segment) => {
    const link = document.createElement("a");
    link.className = "citation-link";
    link.href = segment.url || "#";
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    const label = document.createElement("span");
    label.textContent = segment.source;
    link.append(label, icon("external"));
    list.appendChild(link);
  });
  return list;
}

function renderHandoff(segment, answer, sourceText, conversation) {
  const panel = document.createElement("section");
  panel.className = "handoff-panel";
  const reason = document.createElement("p");
  reason.className = "handoff-reason";
  reason.textContent = segment.reason;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "handoff-btn";
  button.textContent = "Chuyển cán bộ khuyến nông";
  const result = document.createElement("p");
  result.className = "handoff-result";
  result.hidden = true;
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Đang gửi...";
    try {
      const response = await fetch("/api/handoff", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: conversation.sessionId, transcript: sourceText, slots: answer.slots }),
      });
      if (!response.ok) throw new Error("handoff failed");
      const data = await response.json();
      button.textContent = "Đã chuyển cán bộ";
      result.textContent = `Mã yêu cầu #${data.ticket_id}`;
      result.hidden = false;
    } catch (_error) {
      button.disabled = false;
      button.textContent = "Thử chuyển lại";
      result.textContent = "Chưa gửi được yêu cầu.";
      result.hidden = false;
    }
  });
  panel.append(reason, button, result);
  return panel;
}

function submitTypedText(event) {
  if (event) event.preventDefault();
  const text = els.textInput.value.trim();
  if (!text || state.isBusy) return;
  els.textInput.value = "";
  autoSizeTextarea(els.textInput);
  updateSendState();
  submitQuestion(text);
}

function submitQuestion(text) {
  const cleanText = String(text || "").trim();
  if (!cleanText || state.isBusy) return;
  const conversation = ensureConversation();
  const firstMessage = conversation.messages.length === 0;
  const message = {
    id: makeId("message"),
    text: cleanText,
    revisions: [],
    answer: null,
    error: null,
    status: "loading",
    region: conversation.region,
    createdAt: new Date().toISOString(),
  };
  conversation.messages.push(message);
  if (firstMessage && !conversation.titleEdited) conversation.title = titleFromQuestion(cleanText);
  conversation.updatedAt = new Date().toISOString();
  state.editingMessageId = null;
  saveConversations(conversation);
  renderAll();
  scrollToBottom();
  return askBackend(conversation, message);
}

function editQuestion(messageId, nextText) {
  const conversation = getActiveConversation();
  const message = conversation?.messages.find((item) => item.id === messageId);
  const cleanText = String(nextText || "").trim();
  if (!message || !cleanText || state.isBusy) return;
  if (cleanText === message.text) {
    state.editingMessageId = null;
    renderChat();
    return;
  }
  message.revisions = Array.isArray(message.revisions) ? message.revisions : [];
  message.revisions.push({ text: message.text, editedAt: new Date().toISOString() });
  message.text = cleanText;
  message.answer = null;
  message.error = null;
  message.status = "loading";
  message.region = conversation.region;
  if (conversation.messages[0]?.id === message.id && !conversation.titleEdited) {
    conversation.title = titleFromQuestion(cleanText);
  }
  conversation.updatedAt = new Date().toISOString();
  state.editingMessageId = null;
  saveConversations(conversation);
  renderAll();
  askBackend(conversation, message);
}

function retryQuestion(messageId) {
  const conversation = getActiveConversation();
  const message = conversation?.messages.find((item) => item.id === messageId);
  if (!message || state.isBusy) return;
  message.answer = null;
  message.error = null;
  message.status = "loading";
  message.region = conversation.region;
  conversation.updatedAt = new Date().toISOString();
  saveConversations(conversation);
  renderAll();
  scrollToBottom();
  askBackend(conversation, message);
}

async function askBackend(conversation, message) {
  state.isBusy = true;
  updateSendState();
  setStatus("Đang tra danh mục và nguồn địa phương...");
  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: message.text, region: message.region || conversation.region, session_id: conversation.sessionId }),
    });
    if (!response.ok) throw new Error("request failed");
    message.answer = await response.json();
    message.error = null;
    message.status = "done";
  } catch (_error) {
    message.answer = null;
    message.error = "Không kết nối được máy chủ. Bác thử gửi lại câu hỏi sau ít phút.";
    message.status = "error";
  } finally {
    conversation.updatedAt = new Date().toISOString();
    saveConversations(conversation);
    state.isBusy = false;
    setStatus("");
    updateSendState();
    renderAll();
    scrollToBottom();
  }
}

function setupMic() {
  let mediaRecorder = null;
  let chunks = [];
  let stream = null;
  let autoStopTimer = null;
  let phase = "idle";
  let sendOnStop = true;

  function updateMicButton(nextPhase) {
    phase = nextPhase;
    const recording = phase === "recording";
    const waiting = phase === "requesting" || phase === "stopping";
    if (recording) els.micBtn.classList.add("is-recording");
    else els.micBtn.classList.remove("is-recording");
    if (waiting) els.micBtn.classList.add("is-requesting");
    else els.micBtn.classList.remove("is-requesting");
    els.micBtn.setAttribute("aria-pressed", recording ? "true" : "false");
    els.micBtn.setAttribute("aria-busy", waiting ? "true" : "false");

    if (recording) {
      els.micBtn.setAttribute("aria-label", "Dừng và gửi giọng nói");
      els.micBtn.title = "Dừng và gửi";
    } else if (phase === "requesting") {
      els.micBtn.setAttribute("aria-label", "Đang mở micro");
      els.micBtn.title = "Đang mở micro";
    } else if (phase === "stopping") {
      els.micBtn.setAttribute("aria-label", "Đang hoàn tất ghi âm");
      els.micBtn.title = "Đang hoàn tất";
    } else {
      els.micBtn.setAttribute("aria-label", "Bắt đầu ghi âm");
      els.micBtn.title = "Nhấn để nói";
    }
  }

  function stopStreamTracks(targetStream) {
    if (targetStream) targetStream.getTracks().forEach((track) => track.stop());
  }

  function micErrorMessage(error) {
    if (error?.name === "NotFoundError") return "Không tìm thấy micro trên thiết bị này.";
    if (error?.name === "NotReadableError") return "Micro đang được ứng dụng khác sử dụng.";
    if (error?.name === "NotAllowedError" || error?.name === "SecurityError") {
      return "Chưa có quyền dùng mic. Bác hãy cho phép micro rồi thử lại.";
    }
    return "Không mở được micro. Bác có thể gõ câu hỏi hoặc thử tải lại trang.";
  }

  async function start() {
    if (state.isBusy || phase !== "idle") return;
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      setStatus("Trình duyệt này chưa hỗ trợ ghi âm.");
      els.textInput.focus();
      return;
    }
    updateMicButton("requesting");
    setStatus("Đang mở micro...");
    let requestedStream = null;
    try {
      requestedStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Nếu trạng thái đã bị hủy trong lúc hộp thoại quyền đang mở, không được
      // khởi động một recorder muộn ngoài ý muốn của người dùng.
      if (phase !== "requesting") {
        stopStreamTracks(requestedStream);
        return;
      }
      stream = requestedStream;
      const mimeType = [
        "audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4",
      ].find(
        (type) => window.MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(type)
      );
      mediaRecorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      chunks = [];
      sendOnStop = true;
      const recorder = mediaRecorder;
      mediaRecorder.addEventListener("dataavailable", (event) => {
        if (event.data && event.data.size > 0) chunks.push(event.data);
      });
      mediaRecorder.addEventListener("stop", () => { void onRecordingStopped(recorder); });
      mediaRecorder.addEventListener("error", () => {
        sendOnStop = false;
        setStatus("Ghi âm bị gián đoạn. Bác thử lại nhé.");
        if (phase === "recording") stop({ send: false });
      });
      mediaRecorder.start();
      updateMicButton("recording");
      setStatus("Đang nghe... nhấn lại nút mic để dừng và gửi.");
      autoStopTimer = setTimeout(() => {
        if (phase === "recording") stop();
      }, 15000);
    } catch (error) {
      stopStreamTracks(requestedStream);
      stream = null;
      mediaRecorder = null;
      updateMicButton("idle");
      setStatus(micErrorMessage(error));
      els.textInput.focus();
    }
  }

  function stop({ send = true } = {}) {
    if (phase !== "recording" || !mediaRecorder) return;
    clearTimeout(autoStopTimer);
    autoStopTimer = null;
    sendOnStop = send;
    updateMicButton("stopping");
    const recorder = mediaRecorder;
    if (recorder.state !== "inactive") {
      recorder.stop();
    } else {
      void onRecordingStopped(recorder);
    }
  }

  async function onRecordingStopped(recorder) {
    // Bỏ event trễ của một recorder đã được hoàn tất trước đó.
    if (recorder !== mediaRecorder) return;
    clearTimeout(autoStopTimer);
    autoStopTimer = null;
    const recordedChunks = chunks;
    const shouldSend = sendOnStop;
    const blobType = recorder.mimeType || "audio/webm";
    chunks = [];
    mediaRecorder = null;
    stopStreamTracks(stream);
    stream = null;
    updateMicButton("idle");

    if (!shouldSend) return;
    if (!recordedChunks.length) {
      setStatus("Không nghe được nội dung. Bác thử lại nhé.");
      return;
    }
    const blob = new Blob(recordedChunks, { type: blobType });
    await sendAudioForTranscription(blob);
  }

  // Click-to-toggle: một cú tap bắt đầu ghi và không còn bị pointerup dừng ngay;
  // tap lần hai mới dừng/gửi. Sự kiện click chuẩn cũng hỗ trợ Enter/Space cho
  // người dùng bàn phím mà không cần hai nhánh keydown/keyup dễ tạo race.
  els.micBtn.addEventListener("click", (event) => {
    event.preventDefault();
    if (phase === "recording") stop();
    else if (phase === "idle") void start();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden && phase === "requesting") {
      // Hộp thoại quyền có thể hoàn tất sau khi người dùng đã rời trang. Đổi
      // phase để start() nhận ra request cũ và đóng stream ngay khi nó resolve.
      updateMicButton("idle");
      setStatus("Đã hủy mở micro vì ứng dụng chuyển sang nền.");
      return;
    }
    if (document.hidden && phase === "recording") {
      setStatus("Ghi âm đã dừng vì ứng dụng chuyển sang nền.");
      stop({ send: false });
    }
  });
  updateMicButton("idle");
}

function audioFileName(mimeType) {
  const normalized = String(mimeType || "").toLowerCase();
  if (normalized.includes("ogg")) return "clip.ogg";
  if (normalized.includes("mp4") || normalized.includes("m4a")) return "clip.m4a";
  if (normalized.includes("wav")) return "clip.wav";
  return "clip.webm";
}

async function sendAudioForTranscription(blob) {
  state.isBusy = true;
  updateSendState();
  setStatus("Đang nhận diện giọng nói...");
  try {
    const form = new FormData();
    form.append("audio", blob, audioFileName(blob.type));
    const response = await fetch("/api/transcribe", { method: "POST", body: form });
    const body = await safeJson(response);
    if (!response.ok) throw new Error(body.detail || "Không nhận diện được giọng nói.");
    const text = String(body.text || "").trim();
    if (!text) throw new Error("Không nghe rõ nội dung. Bác thử lại nhé.");
    state.isBusy = false;
    await submitQuestion(text);
  } catch (error) {
    setStatus(error.message || "Không nhận diện được giọng nói. Bác có thể gõ câu hỏi.");
    els.textInput.focus();
  } finally {
    state.isBusy = false;
    updateSendState();
  }
}

function autoSizeTextarea(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
}

function updateSendState() {
  els.sendTextBtn.disabled = state.isBusy || !els.textInput.value.trim();
  els.textInput.disabled = state.isBusy;
  els.micBtn.disabled = state.isBusy;
}

function setStatus(message) { els.statusLine.textContent = message || ""; }

function scrollToBottom(smooth = true) {
  requestAnimationFrame(() => {
    els.chat.scrollTo({ top: els.chat.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  });
}

function openSidebar() {
  document.body.classList.add("sidebar-visible");
  els.sidebarClose.focus();
}

function closeSidebar() {
  document.body.classList.remove("sidebar-visible");
}

async function safeJson(response) {
  try { return await response.json(); } catch (_error) { return {}; }
}

function registerServiceWorker() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
}
