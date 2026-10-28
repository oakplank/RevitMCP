(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const providers = {openrouter: "OpenRouter", openai: "OpenAI", anthropic: "Anthropic", google: "Google", xai: "xAI"};
  const keyNames = Object.fromEntries(Object.keys(providers).map(p => [p, "revitMCP_" + p + "_api_key"]));
  const modelCatalog = JSON.parse($("ai-catalog").textContent);
  const keyLinks = {openrouter: "https://openrouter.ai/settings/keys", openai: "https://platform.openai.com/api-keys",
    anthropic: "https://platform.claude.com/settings/keys", google: "https://aistudio.google.com/apikey", xai: "https://console.x.ai/"};
  let connection = read("revitMCP_provider", "openrouter");
  if (!(connection in providers) && connection !== "echo") connection = "openrouter";
  let customModels = readJSON("revitMCP_custom_models", {});
  if (!customModels || typeof customModels !== "object" || Array.isArray(customModels)) customModels = {};
  const legacyCustom = read("revitMCP_custom_model_id"), legacyProvider = read("revitMCP_custom_model_provider");
  if (legacyCustom && legacyProvider in providers && !customModels[legacyProvider]) customModels[legacyProvider] = legacyCustom;
  let settingsProvider = connection;
  let settingsKeys = {};
  let settingsCustomModels = {};
  let chats = {};
  let activeId = "";
  let pending = false;
  let editingId = null;
  let deletedChat = null;
  let toastTimer;
  let contextBusy = false;

  function read(key, fallback = "") {
    try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
  }
  function write(key, value) {
    try { localStorage.setItem(key, value); return true; }
    catch { showToast("Browser storage is full or unavailable. This session is not saved."); return false; }
  }
  function readJSON(key, fallback) {
    try { return JSON.parse(read(key, JSON.stringify(fallback))); } catch { return fallback; }
  }
  function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "icon"); svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS(svg.namespaceURI, "use");
    use.setAttribute("href", "#i-" + name); svg.append(use);
    return svg;
  }
  function title(chat) {
    return chat.metadata?.customTitle || chat.messages.find(m => m.role === "user")?.content.slice(0, 70) || "New chat";
  }
  function currentChat() { return chats[activeId]; }
  function persist() {
    const saved = Object.fromEntries(Object.entries(chats).filter(([, c]) => c.messages.length));
    write("allRevitMCPChats", JSON.stringify(saved, (key, value) => key === "images" ? undefined : value));
    write("revitMCPactiveChat", activeId);
  }
  function initializeChats() {
    const stored = readJSON("allRevitMCPChats", {});
    if (stored && typeof stored === "object" && !Array.isArray(stored)) {
      for (const [id, old] of Object.entries(stored)) {
        const messages = Array.isArray(old) ? old : old?.messages;
        if (!Array.isArray(messages)) continue;
        chats[id] = {
          messages: messages.filter(m => m && typeof m.content === "string" && ["user", "bot", "assistant"].includes(m.role))
            .map(m => ({...m, role: m.role === "assistant" ? "bot" : m.role})),
          metadata: {customTitle: typeof old?.metadata?.customTitle === "string" ? old.metadata.customTitle : ""},
          updatedAt: Number(old?.updatedAt) || Number(id.split("_")[1]) || 0,
          error: typeof old?.error === "string" ? old.error.slice(0, 1400) : ""
        };
      }
    }
    const ids = Object.keys(chats).sort((a, b) => chats[b].updatedAt - chats[a].updatedAt);
    const savedId = read("revitMCPactiveChat");
    if (chats[savedId]) activeId = savedId;
    else if (ids.length) activeId = ids[0];
    else createChat();
    render();
  }
  function createChat() {
    if (pending) return;
    activeId = "chat_" + Date.now() + "_" + Math.random().toString(36).slice(2, 9);
    chats[activeId] = {messages: [], metadata: {}, updatedAt: Date.now(), error: ""};
    $("message-input").value = "";
    $("chat-search").value = "";
    render(); updateComposer(); closeMobileSidebar(); $("message-input").focus();
  }
  function renderHistory() {
    const history = $("chat-history"); history.replaceChildren();
    const query = $("chat-search").value.toLowerCase().trim();
    const entries = Object.entries(chats).filter(([, c]) => c.messages.length && title(c).toLowerCase().includes(query))
      .sort(([, a], [, b]) => b.updatedAt - a.updatedAt);
    for (const [id, chat] of entries) {
      const row = document.createElement("div");
      row.className = "chat-row" + (id === activeId ? " active" : "");
      const link = document.createElement("button");
      link.className = "chat-link"; link.textContent = title(chat); link.title = title(chat); link.disabled = pending;
      if (id === activeId) link.setAttribute("aria-current", "page");
      link.addEventListener("click", () => {
        if (pending) return;
        currentChat().draft = $("message-input").value;
        activeId = id; $("message-input").value = chat.draft || "";
        render(); updateComposer(); persist(); closeMobileSidebar();
      });
      const menu = document.createElement("button");
      menu.className = "chat-menu"; menu.textContent = "⋯"; menu.disabled = pending;
      menu.setAttribute("aria-label", "Options for " + title(chat));
      menu.addEventListener("click", () => {
        editingId = id; $("chat-name").value = title(chat);
        $("chat-dialog").showModal();
      });
      row.append(link, menu); history.append(row);
    }
    $("history-empty").hidden = !!entries.length || !query;
  }

  // Construct message markup from text nodes. Model output never becomes raw HTML.
  function inline(parent, value) {
    const pattern = /(\x60[^\x60\n]+\x60|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\([^\s)]+\))/g;
    let offset = 0;
    for (const match of value.matchAll(pattern)) {
      parent.append(document.createTextNode(value.slice(offset, match.index)));
      const token = match[0];
      let el;
      if (token.startsWith("\x60")) {
        el = document.createElement("code"); el.textContent = token.slice(1, -1);
      } else if (token.startsWith("**")) {
        el = document.createElement("strong"); el.textContent = token.slice(2, -2);
      } else {
        const parts = token.match(/^\[([^\]]+)\]\((.+)\)$/);
        let url;
        try { url = new URL(parts[2]); } catch { url = null; }
        if (url && ["https:", "http:"].includes(url.protocol)) {
          el = document.createElement("a"); el.textContent = parts[1]; el.href = url.href;
          el.target = "_blank"; el.rel = "noopener noreferrer";
        } else { el = document.createTextNode(token); }
      }
      parent.append(el); offset = match.index + token.length;
    }
    parent.append(document.createTextNode(value.slice(offset)));
  }
  function markdown(parent, value) {
    const lines = value.replace(/\r\n/g, "\n").split("\n");
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      if (line.trim().startsWith("\x60\x60\x60")) {
        const block = []; i++;
        while (i < lines.length && !lines[i].trim().startsWith("\x60\x60\x60")) block.push(lines[i++]);
        i++;
        const pre = document.createElement("pre"), code = document.createElement("code");
        code.textContent = block.join("\n"); pre.append(code); parent.append(pre); continue;
      }
      if (/^#{1,6}\s/.test(line)) {
        const h = document.createElement("h3"); inline(h, line.replace(/^#{1,6}\s+/, "")); parent.append(h); i++; continue;
      }
      if (line.includes("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1])) {
        const wrap = document.createElement("div"); wrap.className = "table-scroll";
        const table = document.createElement("table");
        const cells = s => s.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(v => v.trim());
        const head = document.createElement("thead"), tr = document.createElement("tr");
        cells(line).forEach(v => { const th = document.createElement("th"); th.scope = "col"; inline(th, v); tr.append(th); });
        head.append(tr); table.append(head); i += 2;
        const body = document.createElement("tbody");
        while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
          const row = document.createElement("tr");
          cells(lines[i++]).forEach(v => { const td = document.createElement("td"); inline(td, v); row.append(td); });
          body.append(row);
        }
        table.append(body); wrap.append(table); parent.append(wrap); continue;
      }
      if (/^\s*([-*]|\d+\.)\s/.test(line)) {
        const ordered = /^\s*\d+\./.test(line), list = document.createElement(ordered ? "ol" : "ul");
        const itemPattern = ordered ? /^\s*\d+\.\s+/ : /^\s*[-*]\s+/;
        while (i < lines.length && itemPattern.test(lines[i])) {
          const li = document.createElement("li"); inline(li, lines[i++].replace(itemPattern, "")); list.append(li);
        }
        parent.append(list); continue;
      }
      const paragraph = [line]; i++;
      while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*[-*]\s|\s*\d+\.\s|\x60\x60\x60)/.test(lines[i]) &&
        !(lines[i].includes("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1]))) paragraph.push(lines[i++]);
      const p = document.createElement("p"); inline(p, paragraph.join("\n")); parent.append(p);
    }
  }
  function renderActions(parent, actions) {
    if (!Array.isArray(actions) || !actions.length) return;
    const details = document.createElement("details"); details.className = "tool-activity";
    const summary = document.createElement("summary");
    summary.textContent = actions.length + (actions.length === 1 ? " Revit tool used" : " Revit tools used");
    const list = document.createElement("ul");
    for (const action of actions) {
      const item = document.createElement("li"), label = document.createElement("strong"), message = document.createElement("span");
      label.textContent = String(action.name || "Tool").replace(/_/g, " ");
      const failed = ["error", "failed", "partial", "limit_exceeded"].includes(action.status);
      if (failed) item.className = "tool-error";
      message.textContent = String(action.message || action.status || "Finished").slice(0, 400);
      item.append(label, message); list.append(item);
    }
    details.append(summary, list); parent.append(details);
  }
  function renderMessage(message) {
    const article = document.createElement("article");
    article.className = "message " + (message.role === "user" ? "user-message" : "bot-message");
    const label = document.createElement("div"); label.className = "message-label";
    if (message.role !== "user") label.append(icon("model"));
    label.append(document.createTextNode(message.role === "user" ? "You" : "RevitMCP"));
    const copy = document.createElement("button");
    copy.className = "icon-button copy-button"; copy.append(icon("copy")); copy.setAttribute("aria-label", "Copy message");
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(message.content); showToast("Message copied."); }
      catch { showToast("Select the message text to copy it."); }
    });
    label.append(copy); article.append(label);
    renderActions(article, message.actions);
    const body = document.createElement("div"); body.className = "message-body";
    if (message.role === "user") body.textContent = message.content;
    else markdown(body, message.content);
    article.append(body);
    for (const image of message.images || []) {
      if (!/^image\/(png|jpeg|webp)$/.test(image.mime_type || "") || !/^[A-Za-z0-9+/=\s]+$/.test(image.base64_data || "")) continue;
      const img = document.createElement("img");
      img.src = "data:" + image.mime_type + ";base64," + image.base64_data; img.alt = "View exported from Revit"; img.className = "message-image";
      article.append(img);
    }
    $("message-log").append(article);
  }
  function render() {
    const chat = currentChat(); if (!chat) return;
    $("chat-title").textContent = title(chat);
    $("empty-state").hidden = !!chat.messages.length;
    $("message-log").replaceChildren(); chat.messages.forEach(renderMessage);
    $("request-error").hidden = !chat.error;
    $("request-error-text").textContent = chat.error || "";
    renderHistory(); scrollToEnd();
  }
  function scrollToEnd() { $("conversation-scroll").scrollTop = $("conversation-scroll").scrollHeight; }
  function provider() { return connection; }
  function updateComposer() {
    const input = $("message-input");
    input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 170) + "px";
    $("send-button").disabled = pending || !input.value.trim();
  }
  function updateAIStatus() {
    const p = provider(), connected = p === "echo" || !!read(keyNames[p]);
    $("setup-button").hidden = connected;
    $("model-selector").title = p === "echo" ? "Test only. No AI or Revit actions." : "Through " + providers[p];
  }
  function populateModels(preferred = "") {
    const select = $("model-selector"), groups = new Map();
    select.replaceChildren();
    const add = (id, name, group) => {
      if (!groups.has(group)) { const el = document.createElement("optgroup"); el.label = group; groups.set(group, el); select.append(el); }
      const option = document.createElement("option"); option.value = id; option.textContent = name; option.dataset.provider = connection;
      groups.get(group).append(option);
    };
    if (connection === "echo") add("echo_model", "Echo test (no AI)", "Testing");
    else {
      for (const model of modelCatalog) if (model.ids[connection]) add(model.ids[connection], model.name, model.group);
      const custom = customModels[connection];
      if (typeof custom === "string" && custom && !Array.from(select.options).some(o => o.value === custom)) add(custom, custom, "Custom");
    }
    const equivalent = modelCatalog.find(m => Object.values(m.ids).includes(preferred))?.ids[connection];
    const chosen = Array.from(select.options).find(o => o.value === preferred || o.value === equivalent);
    if (chosen) select.value = chosen.value;
    updateAIStatus();
  }
  function stashSettingsFields() {
    if (settingsProvider === "echo") return;
    settingsKeys[settingsProvider] = $("provider-api-key").value.trim();
    settingsCustomModels[settingsProvider] = $("custom-model-id").value.trim();
  }
  function renderConnectionSettings() {
    const p = settingsProvider, isTest = p === "echo";
    $("key-field").hidden = isTest; $("custom-model").hidden = isTest;
    $("provider-api-key").value = settingsKeys[p] || ""; $("provider-api-key").type = "password"; $("show-keys").checked = false;
    $("provider-api-key").placeholder = (providers[p] || "Provider") + " API key";
    $("custom-model-id").value = settingsCustomModels[p] || "";
    $("custom-model-id").placeholder = p === "openrouter" ? "provider/model" : "Model ID";
    $("get-api-key").href = keyLinks[p] || keyLinks.openrouter;
    $("key-privacy").textContent = "Saved in this browser, not in your project. Your RevitMCP server sends the key to " +
      (providers[p] || "the provider") + ". " + (p === "openrouter" ? "OpenRouter and the model provider process your messages." : "This provider processes your messages.");
    $("key-privacy").hidden = true;
    $("settings-feedback").textContent = "";
  }
  function openSettings() {
    settingsKeys = Object.fromEntries(Object.keys(providers).map(p => [p, read(keyNames[p])]));
    settingsCustomModels = {...customModels}; settingsProvider = connection;
    $("connection-selector").value = connection; $("custom-model").open = false;
    renderConnectionSettings();
    $("settings-dialog").showModal();
    if (connection !== "echo" && !read(keyNames[connection])) $("provider-api-key").focus();
  }
  function setPending(value) {
    pending = value; $("pending-message").hidden = !value;
    $("new-chat").disabled = value; $("model-selector").disabled = value;
    document.querySelectorAll("[data-prompt]").forEach(b => b.disabled = value);
    $("composer").setAttribute("aria-busy", String(value));
    renderHistory(); updateComposer();
    if (value) scrollToEnd();
  }
  async function send(event) {
    event.preventDefault();
    const text = $("message-input").value.trim(); if (!text || pending) return;
    const p = provider(), key = p === "echo" ? "" : read(keyNames[p]);
    if (p !== "echo" && !key) { openSettings(); return; }
    const chat = currentChat(), targetId = activeId;
    chat.error = ""; chat.messages.push({role: "user", content: text}); chat.updatedAt = Date.now();
    const payload = {conversation: chat.messages.map(m => ({role: m.role, content: m.content})),
      model: $("model-selector").value, provider: p, apiKey: key};
    $("message-input").value = ""; chat.draft = ""; render(); persist(); setPending(true);
    try {
      const response = await fetch("/chat_api", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
      let data;
      try { data = await response.json(); } catch { throw new Error("The server returned an unreadable response. Check Revit before sending the request again."); }
      const actions = Array.isArray(data.tool_calls) ? data.tool_calls : [];
      const images = Array.isArray(data.images) ? data.images : [];
      if (data.image_output?.status === "success") images.push({mime_type: data.image_output.content_type, base64_data: data.image_output.image_data});
      if (data.reply || actions.length || images.length) chat.messages.push({role: "bot", content: String(data.reply || ""), actions, images});
      if (!response.ok || data.error) throw new Error(data.error || "Request failed (" + response.status + ").");
      if (data.error_detail) chat.error = String(data.error_detail);
      if (!data.reply && !actions.length && !images.length) chat.error = "The provider returned no response. Check your model and API key in Settings.";
    } catch (error) {
      chat.error = error instanceof TypeError ? "The connection was interrupted. Check Revit for any completed changes before sending the request again." : String(error.message).slice(0, 1400);
    } finally {
      chat.updatedAt = Date.now(); persist();
      if (activeId === targetId) render();
      setPending(false); $("message-input").focus(); scrollToEnd(); refreshContext();
    }
  }
  function setSidebar(collapsed) {
    document.body.classList.toggle("sidebar-collapsed", collapsed);
    $("toggle-sidebar").setAttribute("aria-expanded", String(!collapsed));
    $("sidebar-backdrop").hidden = collapsed || !matchMedia("(max-width: 680px)").matches;
    if (!matchMedia("(max-width: 680px)").matches) write("revitMCP_sidebar_closed", String(collapsed));
  }
  function closeMobileSidebar() { if (matchMedia("(max-width: 680px)").matches) setSidebar(true); }
  function showToast(text, undo = false) {
    clearTimeout(toastTimer); $("toast-text").textContent = text;
    $("undo-delete").hidden = !undo; $("toast").hidden = false;
    toastTimer = setTimeout(() => { $("toast").hidden = true; }, undo ? 10000 : 4000);
  }
  async function refreshContext() {
    if (contextBusy) return;
    contextBusy = true; $("check-connection").disabled = true; $("refresh-context").disabled = true;
    $("connection-label").textContent = "Checking Revit";
    try {
      const response = await fetch("/revit_context", {signal: AbortSignal.timeout(9000), cache: "no-store"});
      const data = await response.json();
      if (!response.ok) throw new Error("Revit context is unavailable.");
      const connected = data.status === "connected";
      $("connection-dot").className = "status-dot " + (connected ? "connected" : "disconnected");
      $("connection-label").textContent = connected ? "Revit connected" : "Revit not connected";
      $("model-context").hidden = !connected || !data.document_name;
      $("document-name").textContent = data.document_name || "";
      $("view-name").textContent = data.view_name || "No active view";
      $("selection-count").textContent = Number.isFinite(data.selection_count) ? data.selection_count + " selected" : "";
      $("connection-description").textContent = connected ? (data.document_name ? "Commands use the document active in Revit when they run." : "Revit is connected. Open a project to use model tools.") :
        data.message || "Open Revit and enable pyRevit Routes, then refresh the connection.";
      const details = $("connection-details"); details.replaceChildren();
      if (connected) {
        const entries = [["Document", data.document_name || "No open project"], ["View", data.view_name || "None"],
          ["Selection", Number.isFinite(data.selection_count) ? String(data.selection_count) : "Unavailable"],
          ["Last checked", new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})]];
        for (const [name, value] of entries) { const dt = document.createElement("dt"), dd = document.createElement("dd"); dt.textContent = name; dd.textContent = value; details.append(dt, dd); }
      }
    } catch {
      $("connection-dot").className = "status-dot disconnected"; $("connection-label").textContent = "Revit unavailable";
      $("model-context").hidden = true; $("connection-details").replaceChildren();
      $("connection-description").textContent = "Revit did not respond. Open a project, finish any open Revit dialog, and make sure pyRevit Routes is enabled. Then refresh.";
    } finally { contextBusy = false; $("check-connection").disabled = false; $("refresh-context").disabled = false; }
  }

  $("new-chat").addEventListener("click", createChat);
  $("chat-search").addEventListener("input", renderHistory);
  $("composer").addEventListener("submit", send);
  $("message-input").addEventListener("input", updateComposer);
  $("message-input").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("composer").requestSubmit(); } });
  document.querySelectorAll("[data-prompt]").forEach(b => b.addEventListener("click", () => { $("message-input").value = b.dataset.prompt; updateComposer(); $("message-input").focus(); }));
  $("settings-button").addEventListener("click", openSettings); $("setup-button").addEventListener("click", openSettings);
  $("model-selector").addEventListener("change", () => { write("revitMCPselectedModel", $("model-selector").value); updateAIStatus(); });
  $("settings-form").addEventListener("submit", e => {
    e.preventDefault(); stashSettingsFields(); let saved = true;
    const custom = settingsCustomModels[settingsProvider] || "";
    if (settingsProvider === "openrouter" && custom && !/^[^\s/]+\/[^\s]+$/.test(custom)) {
      $("settings-feedback").textContent = "Use the OpenRouter model ID, such as openai/gpt-6.1-sol."; return;
    }
    for (const p of Object.keys(providers)) saved = write(keyNames[p], settingsKeys[p] || "") && saved;
    saved = write("revitMCP_custom_models", JSON.stringify(settingsCustomModels)) && saved;
    saved = write("revitMCP_provider", settingsProvider) && saved;
    if (saved) {
      const preferred = custom && custom !== customModels[settingsProvider] ? custom : $("model-selector").value;
      connection = settingsProvider; customModels = {...settingsCustomModels}; populateModels(preferred);
      saved = write("revitMCPselectedModel", $("model-selector").value);
      // Retire the legacy single-model storage after a successful migration.
      write("revitMCP_custom_model_id", ""); write("revitMCP_custom_model_provider", "");
    }
    if (saved) { $("settings-dialog").close(); showToast("Settings saved."); $("message-input").focus(); }
    else $("settings-feedback").textContent = "Settings could not be saved. Allow browser storage, then try again.";
  });
  $("connection-selector").addEventListener("change", () => { stashSettingsFields(); settingsProvider = $("connection-selector").value; renderConnectionSettings(); });
  $("show-keys").addEventListener("change", () => { $("provider-api-key").type = $("show-keys").checked ? "text" : "password"; });
  $("settings-dialog").addEventListener("close", () => { $("provider-api-key").value = ""; settingsKeys = {}; $("key-privacy").hidden = true; });
  const showPrivacy = () => { $("key-privacy").hidden = false; };
  $("privacy-button").addEventListener("focus", showPrivacy);
  $("privacy-button").addEventListener("click", showPrivacy);
  $("privacy-help").addEventListener("pointerenter", showPrivacy);
  $("privacy-help").addEventListener("pointerleave", () => { if (document.activeElement !== $("privacy-button")) $("key-privacy").hidden = true; });
  $("privacy-button").addEventListener("blur", () => { $("key-privacy").hidden = true; });
  $("privacy-button").addEventListener("keydown", e => { if (e.key === "Escape" && !$("key-privacy").hidden) { e.preventDefault(); e.stopPropagation(); $("key-privacy").hidden = true; } });
  document.querySelectorAll("[data-close]").forEach(b => b.addEventListener("click", () => $(b.dataset.close).close()));
  $("toggle-sidebar").addEventListener("click", () => setSidebar(!document.body.classList.contains("sidebar-collapsed")));
  $("sidebar-backdrop").addEventListener("click", () => setSidebar(true));
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeMobileSidebar(); });
  const narrow = matchMedia("(max-width: 680px)");
  narrow.addEventListener("change", () => setSidebar(narrow.matches || read("revitMCP_sidebar_closed") === "true"));
  $("connection-button").addEventListener("click", () => $("connection-dialog").showModal());
  $("check-connection").addEventListener("click", refreshContext); $("refresh-context").addEventListener("click", refreshContext);
  $("chat-edit-form").addEventListener("submit", e => {
    e.preventDefault(); const name = $("chat-name").value.trim();
    if (!name || !chats[editingId]) return;
    chats[editingId].metadata.customTitle = name; persist(); render(); $("chat-dialog").close();
  });
  $("delete-chat").addEventListener("click", () => {
    if (!chats[editingId] || pending) return;
    deletedChat = {id: editingId, chat: chats[editingId]}; delete chats[editingId];
    $("chat-dialog").close();
    if (activeId === editingId) createChat(); else renderHistory();
    persist(); showToast("Chat deleted.", true);
  });
  $("undo-delete").addEventListener("click", () => {
    if (!deletedChat) return;
    chats[deletedChat.id] = deletedChat.chat; activeId = deletedChat.id; deletedChat = null;
    persist(); render(); $("toast").hidden = true;
  });

  const preferred = read("revitMCPselectedModel");
  if (!read("revitMCP_provider") && !read(keyNames.openrouter)) {
    const previousProvider = modelCatalog.find(m => Object.values(m.ids).includes(preferred));
    const legacyHint = preferred.startsWith("claude-") ? "anthropic" : preferred.startsWith("gemini-") ? "google" : preferred.startsWith("gpt-") || /^o\d/.test(preferred) ? "openai" : "";
    const direct = previousProvider && Object.keys(previousProvider.ids).find(p => p !== "openrouter" && read(keyNames[p])) || legacyHint && read(keyNames[legacyHint]) && legacyHint;
    // Existing direct keys stay usable; new installs start with OpenRouter.
    connection = direct || Object.keys(providers).find(p => read(keyNames[p])) || connection;
  }
  populateModels(preferred);
  write("revitMCPselectedModel", $("model-selector").value);
  setSidebar(narrow.matches || read("revitMCP_sidebar_closed") === "true");
  initializeChats(); updateAIStatus(); updateComposer(); refreshContext();
})();
