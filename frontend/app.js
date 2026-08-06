/* ABcode 前端逻辑 v0.3.0 */
let state = {
  convs: [],
  currentConvId: null,
  providers: [],
  currentProviderId: "",
  currentModel: "",
  streaming: false,
  editingProviderId: null,
  agentEnabled: true,
  theme: localStorage.getItem("abcode-theme") || "light",
  // 字体设置
  chatFont: localStorage.getItem("abcode-font") || '"PingFang SC", "Microsoft YaHei", "Hiragino Sans GB", sans-serif',
  chatFontSize: parseInt(localStorage.getItem("abcode-fontsize")) || 15,
  chatLineHeight: localStorage.getItem("abcode-lineheight") || "1.7",
  // 提示词建议
  suggestionEnabled: localStorage.getItem("abcode-suggestion") !== "false",
  // 工具栏开关
  tbKb: true,
  tbSkills: true,
  tbMcp: true,
  tbThinking: false,
};

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

// ===== 初始化 =====
async function init() {
  applyTheme(state.theme);
  applyFontSettings();
  applySuggestionSettings();
  await Promise.all([loadProviders(), loadConvs()]);
  bindEvents();
  if (state.providers.length > 0) {
    state.currentProviderId = state.providers[0].id;
    updateProviderSelect();
    const p = getProvider(state.currentProviderId);
    if (p && p.models.length) state.currentModel = p.models[0];
    updateModelSelect();
  }
}

// ===== 个人偏好设置 =====
function adjustFontSize(delta) {
  state.chatFontSize = Math.max(12, Math.min(22, state.chatFontSize + delta));
  document.getElementById("font-size-display").textContent = state.chatFontSize;
  saveFontSettings();
}

function resetPreferences() {
  if (!confirm("确定恢复所有偏好设置为默认值？")) return;
  state.theme = "light";
  state.chatFont = '"PingFang SC", "Microsoft YaHei", "Hiragino Sans GB", sans-serif';
  state.chatFontSize = 15;
  state.chatLineHeight = "1.7";
  state.suggestionEnabled = true;
  state.agentEnabled = true;
  localStorage.removeItem("abcode-theme");
  localStorage.removeItem("abcode-font");
  localStorage.removeItem("abcode-fontsize");
  localStorage.removeItem("abcode-lineheight");
  localStorage.removeItem("abcode-suggestion");
  applyTheme(state.theme);
  applyFontSettings();
  applySuggestionSettings();
  alert("已恢复默认设置");
}

function exportPreferences() {
  const prefs = {
    theme: state.theme,
    chatFont: state.chatFont,
    chatFontSize: state.chatFontSize,
    chatLineHeight: state.chatLineHeight,
    suggestionEnabled: state.suggestionEnabled,
    agentEnabled: state.agentEnabled,
  };
  const blob = new Blob([JSON.stringify(prefs, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "abcode-preferences.json";
  a.click();
  URL.revokeObjectURL(url);
}

// ===== 字体设置 =====
function applyFontSettings() {
  const root = document.documentElement;
  root.style.setProperty("--chat-font", state.chatFont);
  root.style.setProperty("--chat-font-size", state.chatFontSize + "px");
  root.style.setProperty("--chat-line-height", state.chatLineHeight);
}

function saveFontSettings() {
  localStorage.setItem("abcode-font", state.chatFont);
  localStorage.setItem("abcode-fontsize", state.chatFontSize);
  localStorage.setItem("abcode-lineheight", state.chatLineHeight);
  applyFontSettings();
}

// ===== 提示词建议设置 =====
function applySuggestionSettings() {
  const toggle = document.getElementById("suggestion-toggle");
  if (toggle) toggle.checked = state.suggestionEnabled;
}

function saveSuggestionSettings() {
  localStorage.setItem("abcode-suggestion", state.suggestionEnabled);
}

// ===== 生成提示词建议 =====
function generateSuggestions(userMsg, assistantMsg) {
  if (!state.suggestionEnabled) return [];
  // 基于对话内容生成建议
  const suggestions = [];
  const lowerContent = (userMsg + " " + assistantMsg).toLowerCase();
  // 根据内容类型生成相关建议
  if (lowerContent.includes("代码") || lowerContent.includes("编程") || lowerContent.includes("函数")) {
    suggestions.push("帮我优化这段代码");
    suggestions.push("解释一下这段代码的逻辑");
    suggestions.push("添加错误处理");
  } else if (lowerContent.includes("分析") || lowerContent.includes("数据") || lowerContent.includes("统计")) {
    suggestions.push("生成可视化图表");
    suggestions.push("导出分析报告");
    suggestions.push("对比其他方案");
  } else if (lowerContent.includes("写") || lowerContent.includes("文章") || lowerContent.includes("文档")) {
    suggestions.push("帮我润色一下");
    suggestions.push("换个风格重写");
    suggestions.push("扩展更多内容");
  } else if (lowerContent.includes("设计") || lowerContent.includes("架构") || lowerContent.includes("方案")) {
    suggestions.push("评估这个方案的可行性");
    suggestions.push("给出替代方案");
    suggestions.push("详细说明实现步骤");
  } else {
    // 通用建议
    suggestions.push("继续深入探讨");
    suggestions.push("换个角度分析");
    suggestions.push("给出具体示例");
  }
  return suggestions.slice(0, 3);
}

function renderSuggestions(suggestions, containerId) {
  if (!suggestions.length) return;
  const container = document.getElementById(containerId);
  if (!container) return;
  const div = document.createElement("div");
  div.className = "suggestions-container";
  div.innerHTML = `
    <div class="suggestions-label">你可能还想问</div>
    <div class="suggestions-list">
      ${suggestions.map(s => `<div class="suggestion-chip" onclick="useSuggestion('${s.replace(/'/g, "\\'")}')">${s}</div>`).join("")}
    </div>
  `;
  container.appendChild(div);
}

function useSuggestion(text) {
  const input = document.getElementById("chat-input");
  if (input) {
    input.value = text;
    input.focus();
  }
}

// ===== 团队协作 =====
let currentExpertId = null;

async function loadTeamMembers() {
  const members = await api("/api/team/members");
  const list = $("#team-members-list");
  if (!members.length) {
    list.innerHTML = '<div class="empty-state">暂无团队成员</div>';
    return;
  }
  list.innerHTML = members.map(m => `
    <div class="team-member-card">
      <span class="team-member-avatar">${m.avatar || '👤'}</span>
      <div class="team-member-info">
        <div class="team-member-name">${m.name}</div>
        <div class="team-member-email">${m.email || '未设置邮箱'}</div>
      </div>
      <span class="team-member-role role-${m.role}">${m.role === 'admin' ? '管理员' : m.role === 'viewer' ? '观察者' : '成员'}</span>
      <button class="btn-delete" onclick="deleteMember('${m.id}')">🗑</button>
    </div>
  `).join('');
}

function showAddMemberForm() {
  $("#add-member-form").style.display = "flex";
  $("#member-name").focus();
}

function hideAddMemberForm() {
  $("#add-member-form").style.display = "none";
  $("#member-name").value = "";
  $("#member-email").value = "";
}

async function saveMember() {
  const name = $("#member-name").value.trim();
  const email = $("#member-email").value.trim();
  const role = $("#member-role").value;
  if (!name) { alert("请输入姓名"); return; }
  await api("/api/team/members", {
    method: "POST",
    body: JSON.stringify({ name, email, role }),
  });
  hideAddMemberForm();
  loadTeamMembers();
}

async function deleteMember(mid) {
  if (!confirm("确定删除此成员？")) return;
  await api(`/api/team/members/${mid}`, { method: "DELETE" });
  loadTeamMembers();
}

async function loadTeamActivity() {
  const activity = await api("/api/team/activity?limit=30");
  const list = $("#team-activity-list");
  if (!activity.length) {
    list.innerHTML = '<div class="empty-state">暂无活动记录</div>';
    return;
  }
  list.innerHTML = activity.map(a => `
    <div class="team-member-card">
      <div class="team-member-info">
        <div class="team-member-name">${a.user_id} ${a.action} ${a.target_type}</div>
        <div class="team-member-email">${new Date(a.created_at * 1000).toLocaleString()}</div>
      </div>
    </div>
  `).join('');
}

async function loadSharedConversations() {
  const shared = await api("/api/team/shared");
  const list = $("#team-shared-list");
  if (!shared.length) {
    list.innerHTML = '<div class="empty-state">暂无共享对话</div>';
    return;
  }
  list.innerHTML = shared.map(s => `
    <div class="team-member-card">
      <div class="team-member-info">
        <div class="team-member-name">对话: ${s.conv_id}</div>
        <div class="team-member-email">共享者: ${s.shared_by} | 权限: ${s.permission}</div>
      </div>
    </div>
  `).join('');
}

// ===== 专家套件 =====
async function loadExperts(category = null) {
  const url = category && category !== 'all' ? `/api/experts?category=${category}` : "/api/experts";
  const experts = await api(url);
  const grid = $("#expert-grid");
  grid.innerHTML = experts.map(e => `
    <div class="expert-card" onclick="showExpertDetail('${e.id}')">
      <span class="expert-icon">${e.icon}</span>
      <div class="expert-name">${e.name}</div>
      <div class="expert-desc">${e.description}</div>
    </div>
  `).join('');
}

async function showExpertDetail(eid) {
  const e = await api(`/api/experts/${eid}`);
  currentExpertId = eid;
  $("#expert-detail-icon").textContent = e.icon;
  $("#expert-detail-name").textContent = e.name;
  $("#expert-detail-desc").textContent = e.description;
  $("#expert-detail-prompt").value = e.system_prompt;
  $("#expert-detail-tools").innerHTML = (e.tools || []).map(t =>
    `<span class="expert-tool-tag">${t}</span>`
  ).join('') || '<span class="expert-tool-tag">无</span>';
  $("#expert-detail-model").textContent = e.model_preference || '自动选择';
  $("#expert-detail").style.display = "block";
}

async function useCurrentExpert() {
  if (!currentExpertId) return;
  const r = await api(`/api/experts/${currentExpertId}/apply`, { method: "POST" });
  if (r.ok) {
    alert(`已应用专家: ${r.expert.name}\n\n系统提示词已更新，可直接开始对话。`);
    closeModal("expert-modal");
  }
}

// ===== 主题切换 =====
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  state.theme = theme;
  localStorage.setItem("abcode-theme", theme);
  $$(".theme-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.theme === theme);
  });
}

// ===== 通用模态框 =====
function openModal(id) {
  const m = document.getElementById(id);
  if (m) m.style.display = "flex";
}

function closeModal(id) {
  const m = document.getElementById(id);
  if (m) m.style.display = "none";
}

// ===== 数据加载 =====
async function api(path, opts = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!resp.ok) {
    const t = await resp.text();
    throw new Error(t);
  }
  return resp.json();
}

async function loadConvs() {
  state.convs = await api("/api/conversations");
  renderConvList();
  if (state.currentConvId) {
    const conv = state.convs.find((c) => c.id === state.currentConvId);
    if (conv) $("#conv-title").textContent = conv.title || "新对话";
  }
}

async function loadProviders() {
  state.providers = await api("/api/providers");
  renderProviderList();
}

// ===== 会话 =====
async function newChat() {
  if (state.streaming) return;
  const data = await api("/api/conversations", {
    method: "POST",
    body: JSON.stringify({ title: "新对话", model: state.currentModel }),
  });
  state.currentConvId = data.id;
  await loadConvs();
  selectConv(data.id);
}

function selectConv(id) {
  state.currentConvId = id;
  $$(".conv-item").forEach((el) => el.classList.toggle("active", el.dataset.id === id));
  const conv = state.convs.find((c) => c.id === id);
  $("#conv-title").textContent = conv ? conv.title : "";
  loadMessages(id);
}

async function loadMessages(convId) {
  const msgs = await api(`/api/conversations/${convId}/messages`);
  const area = $("#messages");
  area.innerHTML = "";
  $("#welcome").style.display = msgs.length ? "none" : "block";
  msgs.forEach((m) => appendMessage(m.role, m.content, false, m.attachments));
  scrollBottom();
}

async function deleteConv(id) {
  if (!confirm("删除该会话？")) return;
  await api(`/api/conversations/${id}`, { method: "DELETE" });
  if (state.currentConvId === id) {
    state.currentConvId = null;
    $("#messages").innerHTML = "";
    $("#welcome").style.display = "block";
  }
  await loadConvs();
}

function renderConvList() {
  const list = $("#conv-list");
  list.innerHTML = "";
  state.convs.forEach((c) => {
    const el = document.createElement("div");
    el.className = "conv-item" + (c.id === state.currentConvId ? " active" : "");
    el.dataset.id = c.id;
    const title = document.createElement("span");
    title.className = "conv-title";
    title.textContent = c.title || "新对话";
    title.onclick = () => selectConv(c.id);
    const del = document.createElement("button");
    del.className = "conv-del";
    del.textContent = "✕";
    del.onclick = (e) => { e.stopPropagation(); deleteConv(c.id); };
    el.appendChild(title);
    el.appendChild(del);
    list.appendChild(el);
  });
}

// ===== 供应商 =====
function getProvider(id) {
  return state.providers.find((p) => p.id === id);
}

function updateProviderSelect() {
  const sel = $("#provider-select");
  sel.innerHTML = "";
  state.providers.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.name;
    sel.appendChild(opt);
  });
  sel.value = state.currentProviderId;
}

function updateModelSelect() {
  const sel = $("#model-select");
  sel.innerHTML = "";
  const p = getProvider(state.currentProviderId);
  if (!p) return;
  let models = p.models || [];
  if (!models.length && p.default_model) models = [p.default_model];
  models.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = m;
    sel.appendChild(opt);
  });
  if (models.includes(state.currentModel)) sel.value = state.currentModel;
  else if (p.default_model) sel.value = p.default_model;
  state.currentModel = sel.value;
}

function renderProviderList() {
  const list = $("#provider-list");
  list.innerHTML = "";
  state.providers.forEach((p) => {
    const el = document.createElement("div");
    el.className = "provider-item";
    el.innerHTML = `
      <div>
        <div class="pi-name">${esc(p.name)}</div>
        <div class="pi-url">${esc(p.base_url)} · ${(p.models || []).length} 模型</div>
      </div>
      <div class="pi-actions">
        <button onclick="openProviderModal('${p.id}')">编辑</button>
        <button class="pi-del" onclick="deleteProvider('${p.id}')">删除</button>
      </div>`;
    list.appendChild(el);
  });
}

function openProviderModal(id = "") {
  state.editingProviderId = id;
  $("#provider-modal-title").textContent = id ? "编辑供应商" : "添加供应商";
  if (id) {
    const p = getProvider(id);
    $("#pf-name").value = p.name;
    $("#pf-url").value = p.base_url;
    $("#pf-key").value = p.api_key;
    $("#pf-models").value = (p.models || []).join(", ");
    $("#pf-default").value = p.default_model;
    $("#pf-context").value = p.max_context || "";
  } else {
    $("#pf-name").value = "";
    $("#pf-url").value = "";
    $("#pf-key").value = "";
    $("#pf-models").value = "";
    $("#pf-default").value = "";
    $("#pf-context").value = "";
  }
  $("#provider-test-result").style.display = "none";
  $("#model-tags-box").style.display = "none";
  $("#provider-modal").style.display = "flex";
}

function closeProviderModal() {
  $("#provider-modal").style.display = "none";
}

async function saveProvider() {
  const body = {
    id: state.editingProviderId,
    name: $("#pf-name").value.trim(),
    base_url: $("#pf-url").value.trim(),
    api_key: $("#pf-key").value.trim(),
    models: $("#pf-models").value.split(",").map((s) => s.trim()).filter(Boolean),
    default_model: $("#pf-default").value.trim(),
    max_context: parseInt($("#pf-context").value) || 0,
  };
  if (!body.name || !body.base_url) { alert("名称和 Base URL 必填"); return; }
  await api("/api/providers", { method: "POST", body: JSON.stringify(body) });
  closeProviderModal();
  await loadProviders();
  if (!state.currentProviderId || !getProvider(state.currentProviderId)) {
    state.currentProviderId = state.providers[0]?.id || "";
    updateProviderSelect();
  }
  const p = getProvider(state.currentProviderId);
  if (p && p.models.length && !state.currentModel) state.currentModel = p.models[0];
  updateModelSelect();
}

async function deleteProvider(id) {
  if (!confirm("删除该供应商？")) return;
  await api(`/api/providers/${id}`, { method: "DELETE" });
  if (state.currentProviderId === id) {
    state.currentProviderId = state.providers[0]?.id || "";
    state.currentModel = "";
  }
  await loadProviders();
  updateProviderSelect();
  updateModelSelect();
}

async function testProvider() {
  const body = {
    id: state.editingProviderId,
    name: $("#pf-name").value.trim(),
    base_url: $("#pf-url").value.trim(),
    api_key: $("#pf-key").value.trim(),
    models: $("#pf-models").value.split(",").map((s) => s.trim()).filter(Boolean),
    default_model: $("#pf-default").value.trim(),
    max_context: parseInt($("#pf-context").value) || 0,
  };
  const box = $("#provider-test-result");
  box.textContent = "测试中...";
  box.className = "test-result ok";
  box.style.display = "block";
  try {
    const r = await api("/api/providers/test", { method: "POST", body: JSON.stringify(body) });
    box.textContent = r.msg;
    box.className = "test-result " + (r.ok ? "ok" : "fail");
  } catch (e) {
    box.textContent = "测试失败: " + e.message;
    box.className = "test-result fail";
  }
}

// ===== 一键获取模型列表 =====
async function fetchModels() {
  const url = $("#pf-url").value.trim();
  const key = $("#pf-key").value.trim();
  if (!url) { alert("请先填写 Base URL"); return; }
  const btn = $("#fetch-models-btn");
  btn.disabled = true;
  btn.textContent = "⏳ 获取中...";
  try {
    const r = await api("/api/providers/models", {
      method: "POST",
      body: JSON.stringify({ base_url: url, api_key: key }),
    });
    if (r.ok && r.models.length) {
      $("#pf-models").value = r.models.join(", ");
      renderModelTags(r.models, r.free_models || []);
      // 自动填入上下文长度
      if (r.max_context && !$("#pf-context").value) {
        $("#pf-context").value = r.max_context;
      }
    } else {
      alert(r.msg || "未获取到模型列表");
    }
  } catch (e) {
    alert("获取失败: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "🔍 一键获取模型列表";
  }
}

function renderModelTags(models, freeModels) {
  const box = $("#model-tags-box");
  if (!models.length) { box.style.display = "none"; return; }
  box.style.display = "block";
  box.innerHTML = '<div style="font-size:11px;color:var(--text-muted);margin-bottom:6px">点击选择模型（绿色=免费）</div>';
  const freeSet = new Set(freeModels);
  models.forEach((m) => {
    const isFree = freeSet.has(m);
    const tag = document.createElement("span");
    tag.className = "model-tag" + (isFree ? " free-tag" : "");
    tag.textContent = m;
    tag.onclick = () => {
      tag.classList.toggle("selected");
      // 更新输入框
      const selected = [...box.querySelectorAll(".model-tag.selected")].map((t) => t.textContent.replace("免费", "").trim());
      $("#pf-models").value = selected.join(", ");
    };
    box.appendChild(tag);
  });
}

function openSettings() {
  $("#settings-modal").style.display = "flex";
  loadProviders();
  loadSearchSettings();
}
function closeSettings() {
  $("#settings-modal").style.display = "none";
}

// ===== 联网搜索设置 =====
async function loadSearchSettings() {
  try {
    const settings = await api("/api/settings");
    $("#search-engine").value = settings.search_engine || "searxng";
    $("#search-url").value = settings.search_service_url || "";
    $("#search-key").value = settings.search_api_key || "";
  } catch (e) {}
}

async function saveSearchSettings() {
  const body = {
    search_engine: $("#search-engine").value,
    search_service_url: $("#search-url").value.trim(),
    search_api_key: $("#search-key").value.trim(),
  };
  await api("/api/settings", { method: "POST", body: JSON.stringify(body) });
  alert("搜索设置已保存");
}

async function testSearchService() {
  const body = {
    search_engine: $("#search-engine").value,
    search_service_url: $("#search-url").value.trim(),
  };
  const box = $("#search-test-result");
  box.textContent = "测试中...";
  box.className = "test-result ok";
  box.style.display = "block";
  try {
    const r = await api("/api/settings/test-search", { method: "POST", body: JSON.stringify(body) });
    box.textContent = r.msg;
    box.className = "test-result " + (r.ok ? "ok" : "fail");
  } catch (e) {
    box.textContent = "测试失败: " + e.message;
    box.className = "test-result fail";
  }
}

// ===== 知识库 =====
function openKb() {
  $("#kb-modal").style.display = "flex";
  loadKbDocs();
}
function closeKb() {
  $("#kb-modal").style.display = "none";
}

async function loadKbDocs() {
  const docs = await api("/api/kb/docs");
  const list = $("#kb-doc-list");
  list.innerHTML = "";
  if (!docs.length) {
    list.innerHTML = '<p class="hint">知识库为空，上传文档后开始构建。</p>';
    return;
  }
  docs.forEach((d) => {
    const el = document.createElement("div");
    el.className = "kb-doc";
    const t = new Date(d.created_at * 1000).toLocaleString();
    el.innerHTML = `
      <div>
        <div class="kd-name">📄 ${esc(d.name)}</div>
        <div class="kd-meta">${d.chunks} 分块 · ${(d.size / 1024).toFixed(1)}KB · ${t}</div>
      </div>
      <button onclick="deleteKbDoc('${d.id}')">删除</button>`;
    list.appendChild(el);
  });
}

async function uploadKb() {
  const input = $("#kb-file");
  if (!input.files.length) { alert("请选择文件"); return; }
  const files = [...input.files];
  let ok = 0, fail = 0;
  for (const f of files) {
    const fd = new FormData();
    fd.append("file", f);
    try {
      const resp = await fetch("/api/kb/upload", { method: "POST", body: fd });
      if (resp.ok) ok++; else fail++;
    } catch (e) { fail++; }
  }
  alert(`上传完成：成功 ${ok} 个${fail ? `，失败 ${fail} 个` : ""}`);
  input.value = "";
  loadKbDocs();
}

async function deleteKbDoc(id) {
  if (!confirm("删除该文档？")) return;
  await api(`/api/kb/docs/${id}`, { method: "DELETE" });
  loadKbDocs();
}

// ===== 定时任务 =====
function openCron() {
  $("#cron-modal").style.display = "flex";
  loadCronJobs();
}
function closeCron() {
  $("#cron-modal").style.display = "none";
}

async function loadCronJobs() {
  const jobs = await api("/api/cron/jobs");
  const list = $("#cron-job-list");
  list.innerHTML = "";
  if (!jobs.length) {
    list.innerHTML = '<p class="hint">暂无定时任务。</p>';
    return;
  }
  jobs.forEach((j) => {
    const el = document.createElement("div");
    el.className = "cron-job";
    const schedule = j.interval_min > 0
      ? `每 ${j.interval_min} 分钟`
      : (j.schedule_at ? `每日 ${j.schedule_at}` : "手动触发");
    const last = j.last_run ? new Date(j.last_run * 1000).toLocaleString() : "从未";
    el.innerHTML = `
      <div class="cj-head">
        <span class="cj-name">⏰ ${esc(j.name)}</span>
        <span class="cj-badge${j.enabled ? "" : " off"}">${j.enabled ? "启用" : "停用"}</span>
      </div>
      <div class="cj-meta">${schedule} · ${esc(j.prompt.slice(0, 40))}${j.prompt.length > 40 ? "…" : ""}</div>
      <div class="cj-last">上次运行: ${last}${j.last_result ? " · " + esc(j.last_result.slice(0, 30)) : ""}</div>
      <div class="cj-actions">
        <button onclick="runCronNow('${j.id}')">▶ 立即运行</button>
        <button onclick="toggleCron('${j.id}', ${j.enabled ? 0 : 1})">${j.enabled ? "停用" : "启用"}</button>
        <button class="cj-del" onclick="deleteCron('${j.id}')">删除</button>
      </div>`;
    list.appendChild(el);
  });
}

async function saveCron() {
  const body = {
    name: $("#cj-name").value.trim() || "定时任务",
    prompt: $("#cj-prompt").value.trim(),
    interval_min: parseInt($("#cj-interval").value) || 0,
    schedule_at: $("#cj-schedule").value.trim(),
    provider_id: state.currentProviderId,
    model: state.currentModel,
  };
  if (!body.prompt) { alert("任务内容必填"); return; }
  await api("/api/cron/jobs", { method: "POST", body: JSON.stringify(body) });
  $("#cj-name").value = "";
  $("#cj-prompt").value = "";
  loadCronJobs();
}

async function runCronNow(id) {
  await api(`/api/cron/jobs/${id}/run`, { method: "POST" });
  loadCronJobs();
}

async function toggleCron(id, enabled) {
  await api(`/api/cron/jobs/${id}`, { method: "PUT", body: JSON.stringify({ enabled: !!enabled }) });
  loadCronJobs();
}

async function deleteCron(id) {
  if (!confirm("删除该定时任务？")) return;
  await api(`/api/cron/jobs/${id}`, { method: "DELETE" });
  loadCronJobs();
}

// ===== 聊天 =====
function appendMessage(role, content, streaming = false, attachments = []) {
  const area = $("#messages");
  $("#welcome").style.display = "none";
  const el = document.createElement("div");
  el.className = `msg ${role}${streaming ? " streaming" : ""}`;
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "我" : "AB";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (role === "assistant") {
    bubble.innerHTML = renderMarkdown(content);
    decorateCodeBlocks(bubble);
    // 朗读按钮
    const spk = document.createElement("button");
    spk.className = "speak-btn";
    spk.textContent = "🔊 朗读";
    spk.title = "语音朗读回复";
    spk.onclick = () => speak(bubble.innerText);
    bubble.appendChild(spk);
  } else {
    bubble.textContent = content;
  }
  // 附件回显
  (attachments || []).forEach((att) => {
    if (att.mime && att.mime.startsWith("image/")) {
      const img = document.createElement("img");
      img.className = "msg-img";
      img.src = `/uploads/${att.filename}`;
      bubble.appendChild(img);
    } else {
      const tag = document.createElement("div");
      tag.className = "att-tag";
      tag.textContent = `📎 ${att.original || att.filename || "附件"}`;
      bubble.appendChild(tag);
    }
  });
  el.appendChild(avatar);
  el.appendChild(bubble);
  area.appendChild(el);
  scrollBottom();
  return { el, bubble };
}

function renderMarkdown(text) {
  // 先提取思考模式内容
  let thinkingHtml = "";
  text = text.replace(/<thinking>([\s\S]*?)<\/thinking>/gi, (match, content) => {
    thinkingHtml = `<details class="thinking-block" open>
      <summary>💭 思考过程</summary>
      <div class="thinking-content">${esc(content.trim())}</div>
    </details>`;
    return "";
  });

  let html;
  try {
    if (typeof marked !== "undefined") {
      html = marked.parse(text, { breaks: true });
    } else {
      html = esc(text).replace(/\n/g, "<br>");
    }
  } catch (e) {
    html = esc(text).replace(/\n/g, "<br>");
  }

  return thinkingHtml + html;
}

function decorateCodeBlocks(root) {
  root.querySelectorAll("pre").forEach((pre) => {
    if (pre.querySelector(".copy-btn")) return;
    const btn = document.createElement("button");
    btn.className = "copy-btn";
    btn.textContent = "复制";
    btn.onclick = () => {
      navigator.clipboard.writeText(pre.innerText);
      btn.textContent = "已复制 ✓";
      setTimeout(() => (btn.textContent = "复制"), 1500);
    };
    pre.appendChild(btn);
    if (typeof hljs !== "undefined") {
      const code = pre.querySelector("code");
      if (code) {
        try { hljs.highlightElement(code); } catch (e) {}
      }
    }
  });
}

function scrollBottom() {
  const area = $("#chat-area");
  area.scrollTop = area.scrollHeight;
}

// ===== 附件上传（图片/视频/文件） =====
let pendingAttachments = [];

function openAttach() {
  $("#file-input").click();
}

function handleFiles(files) {
  for (const f of files) {
    if (f.size > 100 * 1024 * 1024) { alert(`${f.name} 超过 100MB`); continue; }
    const item = { file: f, name: f.name, mime: f.type, localUrl: null };
    if (f.type.startsWith("image/")) {
      item.localUrl = URL.createObjectURL(f);
    }
    pendingAttachments.push(item);
  }
  renderAttachPreview();
}

function renderAttachPreview() {
  const box = $("#attach-preview");
  box.innerHTML = "";
  pendingAttachments.forEach((a, i) => {
    const el = document.createElement("div");
    el.className = "attach-item";
    el.innerHTML = `
      ${a.localUrl ? `<img src="${a.localUrl}">` : ""}
      <div class="att-name">${esc(a.name)}</div>
      <button class="att-x" onclick="removeAttachment(${i})">✕</button>`;
    box.appendChild(el);
  });
}

function removeAttachment(i) {
  pendingAttachments.splice(i, 1);
  renderAttachPreview();
}

async function uploadAttachments() {
  const results = [];
  for (const a of pendingAttachments) {
    const fd = new FormData();
    fd.append("file", a.file);
    try {
      const resp = await fetch("/api/upload", { method: "POST", body: fd });
      if (resp.ok) {
        const data = await resp.json();
        results.push({ filename: data.filename, original: data.original, mime: data.mime, size: data.size });
      }
    } catch (e) {}
  }
  pendingAttachments = [];
  renderAttachPreview();
  return results.filter(Boolean);
}

// ===== 知识库快捷引用 =====
let kbRefTimer = null;

function openKbRef() {
  const panel = $("#kb-ref-panel");
  panel.style.display = "flex";
  $("#kb-ref-input").value = "";
  $("#kb-ref-input").focus();
  $("#kb-ref-results").innerHTML = '<div class="kb-ref-empty">输入关键词搜索知识库</div>';
}

function closeKbRef() {
  $("#kb-ref-panel").style.display = "none";
}

async function searchKbRef(query) {
  if (!query.trim()) {
    $("#kb-ref-results").innerHTML = '<div class="kb-ref-empty">输入关键词搜索知识库</div>';
    return;
  }
  try {
    const results = await api("/api/kb/search", {
      method: "POST",
      body: JSON.stringify({ query, top_k: 5 }),
    });
    if (!results.length) {
      $("#kb-ref-results").innerHTML = '<div class="kb-ref-empty">未找到相关内容</div>';
      return;
    }
    const box = $("#kb-ref-results");
    box.innerHTML = "";
    results.forEach((r) => {
      const el = document.createElement("div");
      el.className = "kb-ref-result";
      el.innerHTML = `
        <div class="krr-doc">📄 ${esc(r.doc_name)} (相关度: ${r.score})</div>
        <div class="krr-content">${esc(r.content.slice(0, 300))}</div>`;
      el.onclick = () => insertKbRef(r);
      box.appendChild(el);
    });
  } catch (e) {
    $("#kb-ref-results").innerHTML = `<div class="kb-ref-empty">搜索失败: ${e.message}</div>`;
  }
}

function insertKbRef(result) {
  const input = $("#chat-input");
  const ref = `\n[引用知识库「${result.doc_name}」]\n${result.content}\n[/引用]\n`;
  const pos = input.selectionStart;
  input.value = input.value.slice(0, pos) + ref + input.value.slice(pos);
  input.focus();
  autoResize();
  closeKbRef();
}

// ===== 语音输入（Web Speech API） =====
let recognition = null;
let recording = false;

function initSpeech() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    $("#voice-btn").style.display = "none";
    return;
  }
  recognition = new SR();
  recognition.lang = "zh-CN";
  recognition.interimResults = false;
  recognition.continuous = false;
  recognition.onresult = (e) => {
    const text = e.results[0][0].transcript;
    $("#chat-input").value += text;
    autoResize();
    stopRecording();
  };
  recognition.onerror = () => stopRecording();
  recognition.onend = () => { recording = false; $("#voice-btn").classList.remove("recording"); };
}

function toggleVoice() {
  if (!recognition) return;
  if (recording) { stopRecording(); return; }
  recording = true;
  $("#voice-btn").classList.add("recording");
  try { recognition.start(); } catch (e) {}
}

function stopRecording() {
  recording = false;
  $("#voice-btn").classList.remove("recording");
  try { recognition.stop(); } catch (e) {}
}

// ===== 语音朗读（后端 say TTS） =====
async function speak(text) {
  const clean = text.replace(/[#*`>|]/g, "").slice(0, 300);
  if (!clean) return;
  try {
    const resp = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: clean }),
    });
    if (!resp.ok) { alert("语音合成失败"); return; }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    new Audio(url).play();
  } catch (e) {}
}

// ===== 技能 / MCP / 连接器面板 =====
function openTools() {
  $("#tools-modal").style.display = "flex";
  loadSkills();
  loadMcps();
  loadConnectors();
}
function closeTools() { $("#tools-modal").style.display = "none"; }
function switchTab(tab) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
  $$(".tab-panel").forEach((p) => (p.style.display = "none"));
  $("#tab-" + tab).style.display = "block";
}

async function loadSkills() {
  const skills = await api("/api/skills");
  const list = $("#skill-list");
  list.innerHTML = "";
  if (!skills.length) { list.innerHTML = '<p class="hint">暂无技能</p>'; return; }
  skills.forEach((s) => {
    const el = document.createElement("div");
    el.className = "ext-item";
    el.innerHTML = `
      <div class="ei-info">
        <div class="ei-name">${s.builtin ? '<span class="badge-b">内置</span>' : ""} ${esc(s.name)} ${s.enabled ? "" : '<span style="color:#9ca3af">(停用)</span>'}</div>
        <div class="ei-desc">${esc(s.description || "无描述")}</div>
      </div>
      <div class="ei-actions">
        <button class="${s.enabled ? "on" : ""}" onclick="toggleSkill('${s.id}')">${s.enabled ? "已启用" : "已停用"}</button>
        ${s.builtin ? "" : `<button class="del" onclick="deleteSkill('${s.id}')">删除</button>`}
      </div>`;
    list.appendChild(el);
  });
}

async function saveSkill() {
  const body = {
    name: $("#sk-name").value.trim(),
    description: $("#sk-desc").value.trim(),
    code: $("#sk-code").value,
  };
  if (!body.name || !body.code.trim()) { alert("名称和代码必填"); return; }
  try {
    await api("/api/skills", { method: "POST", body: JSON.stringify(body) });
    $("#sk-name").value = ""; $("#sk-desc").value = ""; $("#sk-code").value = "";
    loadSkills();
  } catch (e) {
    alert("保存失败: " + e.message);
  }
}

async function toggleSkill(id) {
  await api(`/api/skills/${id}/toggle`, { method: "POST" });
  loadSkills();
}

async function deleteSkill(id) {
  if (!confirm("删除该技能？")) return;
  await api(`/api/skills/${id}`, { method: "DELETE" });
  loadSkills();
}

// ----- MCP -----
function mcpFormVisible() {
  const t = $("#mcp-transport").value;
  
  // stdio: 显示命令和参数，隐藏URL
  // http/sse/websocket: 显示URL和headers，隐藏命令和参数
  // unix/tcp: 显示URL，隐藏命令和参数和headers
  
  const showCmd = (t === "stdio");
  const showUrl = (t !== "stdio");
  const showHeaders = (t === "http" || t === "sse" || t === "websocket");
  const showArgs = (t === "stdio");
  
  $("#mcp-cmd-label").style.display = showCmd ? "block" : "none";
  $("#mcp-command").style.display = showCmd ? "block" : "none";
  $("#mcp-args-label").style.display = showArgs ? "block" : "none";
  $("#mcp-args").style.display = showArgs ? "block" : "none";
  $("#mcp-url-label").style.display = showUrl ? "block" : "none";
  $("#mcp-url").style.display = showUrl ? "block" : "none";
  $("#mcp-headers-label").style.display = showHeaders ? "block" : "none";
  $("#mcp-headers").style.display = showHeaders ? "block" : "none";
  
  // 更新URL提示文本
  if (t === "unix") {
    $("#mcp-url").placeholder = "/tmp/mcp.sock";
  } else if (t === "tcp") {
    $("#mcp-url").placeholder = "localhost:8080";
  } else if (t === "sse") {
    $("#mcp-url").placeholder = "https://mcp.example.com/sse";
  } else if (t === "websocket") {
    $("#mcp-url").placeholder = "ws://mcp.example.com/ws";
  } else {
    $("#mcp-url").placeholder = "https://mcp.example.com/mcp";
  }
}

async function loadMcps() {
  const mcps = await api("/api/mcp/servers");
  const list = $("#mcp-list");
  list.innerHTML = "";
  if (!mcps.length) { list.innerHTML = '<p class="hint">暂无 MCP 服务器</p>'; return; }
  mcps.forEach((m) => {
    const info = m.transport === "stdio" ? m.command : m.url;
    const el = document.createElement("div");
    el.className = "ext-item";
    el.innerHTML = `
      <div class="ei-info">
        <div class="ei-name"><span class="badge-b">${m.transport.toUpperCase()}</span> ${esc(m.name)} ${m.enabled ? "" : '<span style="color:#9ca3af">(停用)</span>'}</div>
        <div class="ei-desc">${esc(info)}</div>
      </div>
      <div class="ei-actions">
        <button class="${m.enabled ? "on" : ""}" onclick="toggleMcp('${m.id}')">${m.enabled ? "已启用" : "已停用"}</button>
        <button class="edit" onclick="editMcp('${m.id}')">编辑</button>
        <button class="del" onclick="deleteMcp('${m.id}')">删除</button>
      </div>`;
    list.appendChild(el);
  });
}

async function editMcp(id) {
  const mcps = await api("/api/mcp/servers");
  const m = mcps.find((x) => x.id === id);
  if (!m) return;
  
  // 填充表单
  $("#mcp-name").value = m.name || "";
  $("#mcp-transport").value = m.transport || "stdio";
  $("#mcp-command").value = m.command || "";
  $("#mcp-args").value = JSON.stringify(m.args || []);
  $("#mcp-url").value = m.url || "";
  $("#mcp-headers").value = m.headers ? JSON.stringify(m.headers, null, 2) : "";
  
  // 更新表单显示
  mcpFormVisible();
  
  // 滚动到表单
  document.querySelector('.sub-form').scrollIntoView({ behavior: 'smooth' });
}

async function saveMcp() {
  const transport = $("#mcp-transport").value;
  let args = [];
  try { args = JSON.parse($("#mcp-args").value || "[]"); } catch (e) { alert("参数格式错误（需 JSON 数组）"); return; }
  
  // 解析自定义请求头
  let headers = {};
  const headersStr = $("#mcp-headers").value.trim();
  if (headersStr) {
    try { headers = JSON.parse(headersStr); } catch (e) { alert("请求头格式错误（需 JSON 对象）"); return; }
  }
  
  const body = {
    name: $("#mcp-name").value.trim(),
    transport,
    command: $("#mcp-command").value.trim(),
    args,
    url: $("#mcp-url").value.trim(),
    headers,
  };
  
  if (!body.name) { alert("名称必填"); return; }
  
  // 验证必填字段
  if (transport === "stdio" && !body.command) { alert("stdio 需要启动命令"); return; }
  if (transport === "http" && !body.url) { alert("HTTP 需要 URL"); return; }
  if (transport === "sse" && !body.url) { alert("SSE 需要 URL"); return; }
  if (transport === "websocket" && !body.url) { alert("WebSocket 需要 URL"); return; }
  if (transport === "unix" && !body.url) { alert("Unix Socket 需要 Socket 路径"); return; }
  if (transport === "tcp" && !body.url) { alert("TCP 需要 host:port"); return; }
  
  await api("/api/mcp/servers", { method: "POST", body: JSON.stringify(body) });
  $("#mcp-name").value = ""; $("#mcp-command").value = ""; $("#mcp-args").value = ""; 
  $("#mcp-url").value = ""; $("#mcp-headers").value = "";
  loadMcps();
}

async function testMcp() {
  const transport = $("#mcp-transport").value;
  let args = [];
  try { args = JSON.parse($("#mcp-args").value || "[]"); } catch (e) { args = []; }
  
  // 解析自定义请求头
  let headers = {};
  const headersStr = $("#mcp-headers").value.trim();
  if (headersStr) {
    try { headers = JSON.parse(headersStr); } catch (e) { headers = {}; }
  }
  
  const body = {
    name: $("#mcp-name").value.trim(),
    transport,
    command: $("#mcp-command").value.trim(),
    args,
    url: $("#mcp-url").value.trim(),
    headers,
  };
  const box = $("#mcp-test-result");
  box.textContent = "测试中...";
  box.className = "test-result ok";
  box.style.display = "block";
  try {
    const r = await api("/api/mcp/test", { method: "POST", body: JSON.stringify(body) });
    box.textContent = r.msg;
    box.className = "test-result " + (r.ok ? "ok" : "fail");
  } catch (e) {
    box.textContent = "测试失败: " + e.message;
    box.className = "test-result fail";
  }
}

async function toggleMcp(id) {
  const mcps = await api("/api/mcp/servers");
  const m = mcps.find((x) => x.id === id);
  if (!m) return;
  await api("/api/mcp/servers", { method: "POST", body: JSON.stringify({ ...m, enabled: !m.enabled }) });
  loadMcps();
}

async function deleteMcp(id) {
  if (!confirm("删除该 MCP 服务器？")) return;
  await api(`/api/mcp/servers/${id}`, { method: "DELETE" });
  loadMcps();
}

// ----- 连接器 -----
async function loadConnectors() {
  const connectors = await api("/api/connectors");
  const list = $("#connector-list");
  list.innerHTML = "";
  if (!connectors.length) { list.innerHTML = '<p class="hint">暂无连接器</p>'; return; }
  connectors.forEach((c) => {
    const info = c.type === "sqlite" ? (c.config.path || "")
      : (c.type === "mysql" || c.type === "postgres") ? `${c.config.host || ""}:${c.config.port || ""}/${c.config.database || ""}`
      : (c.config.url || c.config.path || "");
    const el = document.createElement("div");
    el.className = "ext-item";
    el.innerHTML = `
      <div class="ei-info">
        <div class="ei-name"><span class="badge-b">${c.type.toUpperCase()}</span> ${esc(c.name)} ${c.enabled ? "" : '<span style="color:#9ca3af">(停用)</span>'}</div>
        <div class="ei-desc">${esc(info)}</div>
      </div>
      <div class="ei-actions">
        <button class="${c.enabled ? "on" : ""}" onclick="toggleConnector('${c.id}')">${c.enabled ? "已启用" : "已停用"}</button>
        <button class="del" onclick="deleteConnector('${c.id}')">删除</button>
      </div>`;
    list.appendChild(el);
  });
}

function onConnectorTypeChange() {
  const type = $("#cn-type").value;
  const isDb = type === "mysql" || type === "postgres";
  $("#cn-simple-fields").style.display = isDb ? "none" : "";
  $("#cn-db-fields").style.display = isDb ? "" : "none";
  $("#cn-path-label").textContent = type === "http" ? "URL" : "文件路径 / URL";
}

async function saveConnector() {
  const type = $("#cn-type").value;
  let config = {};
  if (type === "mysql" || type === "postgres") {
    config = {
      host: $("#cn-host").value.trim(),
      port: $("#cn-port").value.trim() || (type === "mysql" ? "3306" : "5432"),
      database: $("#cn-database").value.trim(),
      user: $("#cn-user").value.trim(),
      password: $("#cn-password").value,
    };
    if (!config.host || !config.database) { alert("主机和数据库名必填"); return; }
  } else {
    const val = $("#cn-config").value.trim();
    config = type === "http" ? { url: val } : { path: val };
    if (!val) { alert("路径/URL 必填"); return; }
  }
  const body = { name: $("#cn-name").value.trim(), type, config };
  if (!body.name) { alert("名称必填"); return; }
  await api("/api/connectors", { method: "POST", body: JSON.stringify(body) });
  $("#cn-name").value = ""; $("#cn-config").value = "";
  $("#cn-host").value = ""; $("#cn-port").value = ""; $("#cn-database").value = "";
  $("#cn-user").value = ""; $("#cn-password").value = "";
  loadConnectors();
}

async function toggleConnector(id) {
  const cs = await api("/api/connectors");
  const c = cs.find((x) => x.id === id);
  if (!c) return;
  await api("/api/connectors", { method: "POST", body: JSON.stringify({ ...c, enabled: !c.enabled }) });
  loadConnectors();
}

async function deleteConnector(id) {
  if (!confirm("删除该连接器？")) return;
  await api(`/api/connectors/${id}`, { method: "DELETE" });
  loadConnectors();
}

// ===== 频道管理 =====
function openChannelModal() {
  $("#channel-modal").style.display = "flex";
  loadChannels();
}
function closeChannelModal() {
  $("#channel-modal").style.display = "none";
}

async function loadChannels() {
  const channels = await api("/api/channels");
  const enabledList = $("#channel-enabled-list");
  const disabledGrid = $("#channel-disabled-grid");
  const enabled = channels.filter((c) => c.enabled);
  const disabled = channels.filter((c) => !c.enabled);

  $("#channel-active-count").textContent = enabled.length;

  // 已激活频道卡片
  enabledList.innerHTML = "";
  if (!enabled.length) {
    enabledList.innerHTML = '<p class="hint">暂无已激活的频道</p>';
  } else {
    enabled.forEach((ch) => {
      const el = document.createElement("div");
      el.className = "channel-enabled-card";
      el.innerHTML = `
        <div class="ch-info">
          <span class="ch-icon">${esc(ch.icon || "📡")}</span>
          <div>
            <div><span class="ch-name">${esc(ch.name)}</span><span class="ch-type-tag">${esc(ch.type)}</span></div>
            <div class="ch-prefix">机器人前缀: ${esc(ch.bot_prefix || "未设置")}</div>
          </div>
        </div>
        <div class="ch-right">
          <span class="ch-status">已启用</span>
          <button class="ch-btn" onclick="toggleChannel('${ch.id}', false)">停用</button>
          ${ch.builtin ? "" : `<button class="ch-btn danger" onclick="deleteChannel('${ch.id}')">删除</button>`}
        </div>`;
      enabledList.appendChild(el);
    });
  }

  // 未激活频道网格
  disabledGrid.innerHTML = "";
  if (!disabled.length) {
    disabledGrid.innerHTML = '<p class="hint" style="grid-column:1/-1;text-align:center;padding:20px;">所有频道均已激活</p>';
  } else {
    disabled.forEach((ch) => {
      const el = document.createElement("div");
      el.className = "channel-grid-item";
      el.innerHTML = `
        <span class="ch-grid-icon">${esc(ch.icon || "📡")}</span>
        <span class="ch-grid-name">${esc(ch.name)}</span>
        <button class="ch-grid-btn" onclick="toggleChannel('${ch.id}', true)">启用</button>`;
      disabledGrid.appendChild(el);
    });
  }
}

async function toggleChannel(id, enable) {
  await api(`/api/channels/${id}/toggle`, { method: "POST" });
  loadChannels();
}

async function deleteChannel(id) {
  if (!confirm("删除该频道？")) return;
  await api(`/api/channels/${id}`, { method: "DELETE" });
  loadChannels();
}

// ===== 会话工具配置 =====
async function openConvTools() {
  if (!state.currentConvId) { alert("请先创建或选择一个会话"); return; }
  const data = await api(`/api/conversations/${state.currentConvId}/tools`);
  $("#ct-skills").innerHTML = renderChecks(data.skills || [], data.skill_ids || [], "skill");
  $("#ct-mcps").innerHTML = renderChecks(data.mcps || [], data.mcp_ids || [], "mcp");
  $("#ct-connectors").innerHTML = renderChecks(data.connectors || [], data.connector_ids || [], "connector");
  $("#convtools-modal").style.display = "flex";
}
function closeConvTools() { $("#convtools-modal").style.display = "none"; }

function renderChecks(items, selected, kind) {
  if (!items.length) return '<p class="hint">暂无可用项</p>';
  return items.map((it) => `
    <label class="ct-check${selected.includes(it.id) ? " active" : ""}">
      <input type="checkbox" data-kind="${kind}" data-id="${it.id}" ${selected.includes(it.id) ? "checked" : ""}>
      ${esc(it.name)}
    </label>`).join("");
}

async function saveConvTools() {
  const collect = (kind) =>
    [...$$(`input[data-kind="${kind}"]:checked`)].map((i) => i.dataset.id);
  await api(`/api/conversations/${state.currentConvId}/tools`, {
    method: "POST",
    body: JSON.stringify({
      skill_ids: collect("skill"),
      mcp_ids: collect("mcp"),
      connector_ids: collect("connector"),
    }),
  });
  closeConvTools();
  alert("已保存本会话工具配置");
}

// ===== 在线更新 =====
async function loadVersion() {
  try {
    const v = await api("/api/version");
    $("#cur-version").textContent = v.version;
  } catch (e) {}
}

// ===== 自动更新 =====
async function saveAutoUpdateSettings() {
  const enabled = $("#auto-update-enabled").checked;
  const interval = $("#auto-update-interval").value;
  await api("/api/settings", {
    method: "POST",
    body: JSON.stringify({
      auto_update_enabled: enabled.toString(),
      auto_update_interval: interval,
    }),
  });
}

async function loadAutoUpdateSettings() {
  try {
    const settings = await api("/api/settings");
    if (settings.auto_update_enabled !== undefined) {
      $("#auto-update-enabled").checked = settings.auto_update_enabled !== "false";
    }
    if (settings.auto_update_interval !== undefined) {
      $("#auto-update-interval").value = settings.auto_update_interval;
    }
    if (settings.update_url !== undefined) {
      $("#update-url").value = settings.update_url;
    }
  } catch (e) {}
}

async function checkUpdate() {
  const url = $("#update-url").value.trim();
  const box = $("#update-result");
  box.style.display = "block";
  box.className = "test-result ok";
  box.textContent = "检查中...";
  
  // 保存更新源设置
  if (url) {
    await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({ update_url: url }),
    });
  }
  
  try {
    const r = await api(`/api/update/check?url=${encodeURIComponent(url)}`);
    if (!r.ok) { box.className = "test-result fail"; box.textContent = r.msg; return; }
    if (!r.has_update) { box.textContent = `${r.msg} (当前 ${r.current})`; return; }
    
    // 显示更新信息
    box.innerHTML = `
      <div style="margin-bottom: 8px;">
        <b>发现新版本 ${r.latest}</b> (当前 ${r.current})
      </div>
      ${r.changelog ? `<div style="margin-bottom: 8px; font-size: 12px; color: var(--text-secondary);">${esc(r.changelog)}</div>` : ''}
      <div style="display: flex; gap: 8px;">
        <button onclick="downloadAndApply('${r.download_url}', '${r.md5 || ''}')" 
                style="padding: 6px 14px; border: none; border-radius: 8px; background: var(--primary); color: white; cursor: pointer;">
          ⬇ 下载并安装
        </button>
        <button onclick="downloadUpdate('${r.download_url}')" 
                style="padding: 6px 14px; border: 1px solid var(--border); border-radius: 8px; background: white; cursor: pointer; color: var(--text-secondary);">
          ⬇ 仅下载
        </button>
      </div>
    `;
  } catch (e) {
    box.className = "test-result fail";
    box.textContent = "检查失败: " + e.message;
  }
}

async function downloadUpdate(url) {
  if (!url) { alert("更新源未提供下载地址"); return; }
  const box = $("#update-result");
  const progress = $("#update-progress");
  const progressText = $("#update-progress-text");
  const progressPercent = $("#update-progress-percent");
  const progressBar = $("#update-progress-bar");
  
  box.innerHTML = "下载中...";
  progress.style.display = "block";
  progressText.textContent = "正在下载更新包...";
  progressBar.style.width = "0%";
  
  // 模拟进度（实际进度需要轮询）
  let progressVal = 0;
  const progressInterval = setInterval(() => {
    if (progressVal < 90) {
      progressVal += Math.random() * 10;
      progressBar.style.width = Math.min(progressVal, 90) + "%";
      progressPercent.textContent = Math.min(Math.round(progressVal), 90) + "%";
    }
  }, 500);
  
  try {
    const r = await api("/api/update/download", { method: "POST", body: JSON.stringify({ url }) });
    clearInterval(progressInterval);
    
    if (r.ok) {
      progressBar.style.width = "100%";
      progressPercent.textContent = "100%";
      progressText.textContent = "下载完成";
      box.innerHTML = `✅ ${r.msg}<br>
        <span style="color:#6b7280;font-size:12px">更新包已保存到: ${esc(r.path)}</span><br>
        <button onclick="applyUpdate('${esc(r.path)}')" 
                style="margin-top:8px;padding:6px 14px;border:none;border-radius:8px;background:var(--primary);color:white;cursor:pointer">
          🔄 应用更新
        </button>`;
    } else {
      progressBar.style.width = "0%";
      progressText.textContent = "下载失败";
      box.className = "test-result fail";
      box.textContent = r.msg;
    }
  } catch (e) {
    clearInterval(progressInterval);
    progressBar.style.width = "0%";
    progressText.textContent = "下载失败";
    box.className = "test-result fail";
    box.textContent = "下载失败: " + e.message;
  }
}

async function downloadAndApply(url, md5) {
  if (!url) { alert("更新源未提供下载地址"); return; }
  const box = $("#update-result");
  const progress = $("#update-progress");
  const progressText = $("#update-progress-text");
  const progressPercent = $("#update-progress-percent");
  const progressBar = $("#update-progress-bar");
  
  box.innerHTML = "下载中...";
  progress.style.display = "block";
  progressText.textContent = "正在下载更新包...";
  progressBar.style.width = "0%";
  
  let progressVal = 0;
  const progressInterval = setInterval(() => {
    if (progressVal < 90) {
      progressVal += Math.random() * 10;
      progressBar.style.width = Math.min(progressVal, 90) + "%";
      progressPercent.textContent = Math.min(Math.round(progressVal), 90) + "%";
    }
  }, 500);
  
  try {
    const r = await api("/api/update/download", { method: "POST", body: JSON.stringify({ url }) });
    clearInterval(progressInterval);
    
    if (r.ok) {
      progressBar.style.width = "100%";
      progressPercent.textContent = "100%";
      progressText.textContent = "正在应用更新...";
      box.innerHTML = "正在应用更新，服务即将重启...";
      
      // 应用更新
      const applyR = await api("/api/update/apply", {
        method: "POST",
        body: JSON.stringify({ zip_path: r.path, md5 }),
      });
      
      if (applyR.ok) {
        box.innerHTML = `✅ ${applyR.msg}<br>
          <span style="color:#6b7280;font-size:12px">页面将在3秒后自动刷新...</span>`;
        setTimeout(() => location.reload(), 3000);
      } else {
        box.className = "test-result fail";
        box.textContent = applyR.msg;
      }
    } else {
      progressBar.style.width = "0%";
      progressText.textContent = "下载失败";
      box.className = "test-result fail";
      box.textContent = r.msg;
    }
  } catch (e) {
    clearInterval(progressInterval);
    progressBar.style.width = "0%";
    progressText.textContent = "操作失败";
    box.className = "test-result fail";
    box.textContent = "操作失败: " + e.message;
  }
}

async function applyUpdate(zipPath) {
  if (!confirm("确定应用更新？更新后服务将自动重启。")) return;
  
  const box = $("#update-result");
  const progress = $("#update-progress");
  const progressText = $("#update-progress-text");
  const progressBar = $("#update-progress-bar");
  
  progress.style.display = "block";
  progressText.textContent = "正在应用更新...";
  progressBar.style.width = "50%";
  
  try {
    const r = await api("/api/update/apply", {
      method: "POST",
      body: JSON.stringify({ zip_path: zipPath }),
    });
    
    if (r.ok) {
      progressBar.style.width = "100%";
      box.innerHTML = `✅ ${r.msg}<br>
        <span style="color:#6b7280;font-size:12px">页面将在3秒后自动刷新...</span>`;
      setTimeout(() => location.reload(), 3000);
    } else {
      box.className = "test-result fail";
      box.textContent = r.msg;
    }
  } catch (e) {
    box.className = "test-result fail";
    box.textContent = "应用更新失败: " + e.message;
  }
}

async function loadUpdateStatus() {
  try {
    const status = await api("/api/update/status");
    const box = $("#update-result");
    box.style.display = "block";
    box.className = "test-result ok";
    
    let html = `<b>更新状态</b><br>`;
    html += `检查中: ${status.checking ? "是" : "否"}<br>`;
    html += `下载中: ${status.downloading ? "是" : "否"}<br>`;
    html += `应用中: ${status.applying ? "是" : "否"}<br>`;
    
    if (status.last_check > 0) {
      const lastCheck = new Date(status.last_check * 1000).toLocaleString();
      html += `上次检查: ${lastCheck}<br>`;
    }
    
    if (status.update_available) {
      html += `<span style="color:var(--primary)">发现新版本 ${status.latest_version}</span><br>`;
    }
    
    if (status.error) {
      html += `<span style="color:#dc2626">错误: ${esc(status.error)}</span><br>`;
    }
    
    box.innerHTML = html;
  } catch (e) {
    const box = $("#update-result");
    box.style.display = "block";
    box.className = "test-result fail";
    box.textContent = "获取状态失败: " + e.message;
  }
}

async function toggleUpdateHistory() {
  const historyDiv = $("#update-history");
  if (historyDiv.style.display === "none") {
    await loadUpdateHistory();
    historyDiv.style.display = "block";
  } else {
    historyDiv.style.display = "none";
  }
}

async function loadUpdateHistory() {
  try {
    const history = await api("/api/update/history");
    const historyDiv = $("#update-history");
    const countSpan = $("#update-history-count");
    
    countSpan.textContent = `(${history.length})`;
    
    if (!history.length) {
      historyDiv.innerHTML = '<p style="font-size: 12px; color: var(--text-muted); padding: 8px;">暂无更新记录</p>';
      return;
    }
    
    historyDiv.innerHTML = history.map(h => {
      const time = new Date(h.time * 1000).toLocaleString();
      const icon = h.result === 'success' ? '✅' : '❌';
      const color = h.result === 'success' ? 'var(--text-secondary)' : '#dc2626';
      return `<div style="padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 12px;">
        <div style="display: flex; justify-content: space-between;">
          <span>${icon} ${h.action}</span>
          <span style="color: ${color}">${h.result}</span>
        </div>
        <div style="color: var(--text-muted); font-size: 11px;">${time}</div>
        ${h.details ? `<div style="color: var(--text-muted); font-size: 11px; margin-top: 2px;">${esc(h.details)}</div>` : ''}
      </div>`;
    }).join('');
  } catch (e) {
    const historyDiv = $("#update-history");
    historyDiv.innerHTML = `<p style="font-size: 12px; color: #dc2626; padding: 8px;">加载失败: ${e.message}</p>`;
  }
}

// ===== 工作流 =====
let currentWorkflow = null;
let currentWfView = "list";
let selectedNode = null;
let draggingNodeType = null;
let wfNodeCounter = 0;

// 画布平移
let wfCanvasPan = { x: 0, y: 0 };
let wfCanvasPanning = false;
let wfCanvasPanStart = { x: 0, y: 0 };
let wfPage = 1;
const wfPageSize = 20;

// 节点连线
let wfConnecting = false;
let wfConnectSource = null;
let wfConnectSourcePos = null;

// 打开工作流弹窗
async function openWorkflow() {
  openModal("workflow-modal");
  await loadWorkflowList();
}

// 加载工作流列表（卡片分页）
let allWorkflows = [];
async function loadWorkflowList() {
  try {
    allWorkflows = await api("/api/workflows");
    wfPage = 1;
    renderWfListPage();
  } catch (e) {
    console.error("加载工作流列表失败:", e);
  }
}

function renderWfListPage() {
  const container = $("#wf-list-content");
  if (!allWorkflows.length) {
    container.innerHTML = `
      <div style="text-align:center; padding:40px 20px;">
        <div style="font-size:48px; margin-bottom:16px;">⚡</div>
        <h3 style="margin:0 0 8px; color:var(--chat-text);">还没有工作流</h3>
        <p style="color:var(--text-muted); margin:0 0 16px;">创建工作流来自动化你的AI任务</p>
        <button class="btn-save" onclick="createNewWorkflow()">＋ 创建第一个工作流</button>
      </div>`;
    return;
  }

  const totalPages = Math.ceil(allWorkflows.length / wfPageSize);
  if (wfPage > totalPages) wfPage = totalPages;
  const start = (wfPage - 1) * wfPageSize;
  const pageData = allWorkflows.slice(start, start + wfPageSize);

  let html = '<div class="wf-card-grid">';
  html += pageData.map(wf => {
    const lastExec = wf.last_execution;
    const status = lastExec ? (lastExec.status === "completed" ? "✅" : "❌") : "";
    const statusText = lastExec ? (lastExec.status === "completed" ? "成功" : "失败") : "未运行";
    const statusClass = lastExec ? (lastExec.status === "completed" ? "wf-status-ok" : "wf-status-fail") : "wf-status-none";
    const timeStr = wf.updated_at ? new Date(wf.updated_at * 1000).toLocaleString() : "";
    const createdStr = wf.created_at ? new Date(wf.created_at * 1000).toLocaleDateString() : "";
    return `
      <div class="wf-card" onclick="openWorkflowEditor('${wf.id}')">
        <div class="wf-card-header">
          <div class="wf-card-icon">⚡</div>
          <div class="wf-card-actions">
            <button class="btn-test" onclick="event.stopPropagation(); showWfObservation('${wf.id}')" title="请求观测" style="padding:2px 6px; font-size:11px;">👁</button>
            <button class="btn-test" onclick="event.stopPropagation(); runWorkflow('${wf.id}')" title="运行" style="padding:2px 6px; font-size:11px;">▶</button>
            <button class="btn-test" onclick="event.stopPropagation(); deleteWorkflow('${wf.id}')" title="删除" style="padding:2px 6px; font-size:11px; color:#ef4444;">🗑</button>
          </div>
        </div>
        <div class="wf-card-name">${esc(wf.name)}</div>
        <div class="wf-card-desc">${esc(wf.description || "无描述")}</div>
        <div class="wf-card-meta">
          <span>${wf.node_count} 个节点</span>
          <span class="${statusClass}">${status} ${statusText}</span>
        </div>
        <div class="wf-card-footer">
          <span class="wf-card-id" title="ID: ${esc(wf.id)}">${esc(wf.id)}</span>
          <span class="wf-card-time">${timeStr || createdStr}</span>
        </div>
      </div>`;
  }).join('');
  html += '</div>';

  // 分页
  if (totalPages > 1) {
    html += `<div class="wf-pagination">
      <button class="btn-test" onclick="wfPage=1;renderWfListPage()" ${wfPage===1?'disabled':''}>⏮</button>
      <button class="btn-test" onclick="wfPage=Math.max(1,wfPage-1);renderWfListPage()" ${wfPage===1?'disabled':''}>◀</button>
      <span class="wf-page-info">第 ${wfPage} / ${totalPages} 页（共 ${allWorkflows.length} 个）</span>
      <button class="btn-test" onclick="wfPage=Math.min(${totalPages},wfPage+1);renderWfListPage()" ${wfPage>=totalPages?'disabled':''}>▶</button>
      <button class="btn-test" onclick="wfPage=${totalPages};renderWfListPage()" ${wfPage>=totalPages?'disabled':''}>⏭</button>
    </div>`;
  } else if (allWorkflows.length > 0) {
    html += `<div class="wf-pagination"><span class="wf-page-info">共 ${allWorkflows.length} 个工作流</span></div>`;
  }

  container.innerHTML = html;
}

// 创建新工作流
function _genWfId(length = 15) {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  let id = "wf_";
  for (let i = 0; i < length; i++) id += chars[Math.floor(Math.random() * chars.length)];
  return id;
}

function createNewWorkflow() {
  currentWorkflow = {
    id: _genWfId(),
    name: "新工作流",
    description: "",
    nodes: [
      { id: "start", type: "start", label: "开始", x: 100, y: 200, config: { input_fields: ["input"] } },
      { id: "end", type: "end", label: "结束", x: 500, y: 200, config: { output_field: "output" } },
    ],
    edges: [{ source: "start", target: "end" }],
    enabled: true,
  };
  openWorkflowEditor(null);
}

// 打开工作流编辑器
async function openWorkflowEditor(wfId) {
  if (wfId) {
    try {
      currentWorkflow = await api(`/api/workflows/${wfId}`);
    } catch (e) {
      alert("加载工作流失败: " + e.message);
      return;
    }
  }
  
  // 确保 start→end 骨干连线存在
  ensureBackboneEdge();
  
  switchWfView("editor");
  $("#wf-name-input").value = currentWorkflow.name || "";
  $("#wf-desc-input").value = currentWorkflow.description || "";
  
  // 重置画布偏移
  wfCanvasPan = { x: 0, y: 0 };
  renderWorkflowCanvas();
  initCanvasPan();
  
  // 如果测试面板是打开的，刷新输入字段
  if (testPanelOpen) initTestPanel();
}

// 切换视图
function switchWfView(view) {
  currentWfView = view;
  $("#wf-list-view").style.display = view === "list" ? "block" : "none";
  $("#wf-editor-view").style.display = view === "editor" ? "block" : "none";
  $("#wf-templates-view").style.display = view === "templates" ? "block" : "none";
  $$(".wf-view-btn").forEach(btn => btn.classList.toggle("active", btn.dataset.view === view));
  
  if (view === "list") loadWorkflowList();
  if (view === "executions") loadWorkflowExecutions();
}

// 渲染工作流画布
function renderWorkflowCanvas() {
  const canvas = $("#wf-canvas");
  const edgesSvg = $("#wf-canvas-edges");
  const container = $("#wf-canvas-container");
  
  canvas.innerHTML = "";
  edgesSvg.innerHTML = "";
  
  if (!currentWorkflow) return;
  
  // 恢复画布偏移
  canvas.style.transform = `translate(${wfCanvasPan.x}px, ${wfCanvasPan.y}px)`;
  edgesSvg.style.transform = `translate(${wfCanvasPan.x}px, ${wfCanvasPan.y}px)`;
  
  // 渲染节点
  currentWorkflow.nodes.forEach(node => {
    const el = document.createElement("div");
    el.className = "wf-node" + (selectedNode === node.id ? " selected" : "");
    el.dataset.id = node.id;
    el.dataset.type = node.type;
    el.style.left = (node.x || 0) + "px";
    el.style.top = (node.y || 0) + "px";
    
    const icon = getNodeIcon(node.type);
    el.innerHTML = `
      <div class="wf-node-header">${icon} ${esc(node.label || node.type)}</div>
      <div class="wf-node-body">${getNodeSummary(node)}</div>
      <div class="wf-node-port wf-port-in" data-port="in" data-id="${node.id}"></div>
      <div class="wf-node-port wf-port-out" data-port="out" data-id="${node.id}"></div>`;
    
    // 点击选中 + 打开配置（区分拖拽）
    let didDrag = false;
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      if (!wfConnecting && !didDrag) {
        selectNode(node.id);
        showNodeConfig(node.id);
      }
    });
    
    // 连线：从 out port 拖出
    const outPort = el.querySelector(".wf-port-out");
    outPort.addEventListener("mousedown", (e) => {
      e.stopPropagation();
      e.preventDefault();
      wfConnecting = true;
      wfConnectSource = node.id;
      const rect = outPort.getBoundingClientRect();
      const cRect = container.getBoundingClientRect();
      wfConnectSourcePos = {
        x: node.x + 160 + wfCanvasPan.x,
        y: node.y + 28 + wfCanvasPan.y
      };
      // 创建临时连线
      let tmpLine = $("#wf-temp-line");
      if (!tmpLine) {
        tmpLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
        tmpLine.id = "wf-temp-line";
        tmpLine.setAttribute("stroke", "var(--primary)");
        tmpLine.setAttribute("stroke-width", "2");
        tmpLine.setAttribute("stroke-dasharray", "6,3");
        tmpLine.style.pointerEvents = "none";
        edgesSvg.appendChild(tmpLine);
      }
      const onMove = (ev) => {
        const cx = ev.clientX - cRect.left + container.scrollLeft;
        const cy = ev.clientY - cRect.top + container.scrollTop;
        tmpLine.setAttribute("x1", wfConnectSourcePos.x);
        tmpLine.setAttribute("y1", wfConnectSourcePos.y);
        tmpLine.setAttribute("x2", cx);
        tmpLine.setAttribute("y2", cy);
      };
      const onUp = (ev) => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        if (tmpLine && tmpLine.parentNode) tmpLine.remove();
        // 检查是否松在某个 in port 上
        const target = document.elementFromPoint(ev.clientX, ev.clientY);
        if (target && target.classList.contains("wf-port-in") && target.dataset.id !== wfConnectSource) {
          const targetId = target.dataset.id;
          // 检查是否已存在该连线
          const exists = currentWorkflow.edges.some(e => e.source === wfConnectSource && e.target === targetId);
          if (!exists) {
            currentWorkflow.edges.push({ source: wfConnectSource, target: targetId });
            renderEdges();
          }
        }
        wfConnecting = false;
        wfConnectSource = null;
        wfConnectSourcePos = null;
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
    
    // 从 in port 拖出也能连线（反向）
    const inPort = el.querySelector(".wf-port-in");
    inPort.addEventListener("mousedown", (e) => {
      e.stopPropagation();
      e.preventDefault();
      wfConnecting = true;
      wfConnectSource = node.id;
      const cRect = container.getBoundingClientRect();
      wfConnectSourcePos = {
        x: node.x + wfCanvasPan.x,
        y: node.y + 28 + wfCanvasPan.y
      };
      let tmpLine = $("#wf-temp-line");
      if (!tmpLine) {
        tmpLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
        tmpLine.id = "wf-temp-line";
        tmpLine.setAttribute("stroke", "var(--primary)");
        tmpLine.setAttribute("stroke-width", "2");
        tmpLine.setAttribute("stroke-dasharray", "6,3");
        tmpLine.style.pointerEvents = "none";
        edgesSvg.appendChild(tmpLine);
      }
      const onMove = (ev) => {
        const cx = ev.clientX - cRect.left + container.scrollLeft;
        const cy = ev.clientY - cRect.top + container.scrollTop;
        tmpLine.setAttribute("x1", wfConnectSourcePos.x);
        tmpLine.setAttribute("y1", wfConnectSourcePos.y);
        tmpLine.setAttribute("x2", cx);
        tmpLine.setAttribute("y2", cy);
      };
      const onUp = (ev) => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        if (tmpLine && tmpLine.parentNode) tmpLine.remove();
        const target = document.elementFromPoint(ev.clientX, ev.clientY);
        if (target && target.classList.contains("wf-port-out") && target.dataset.id !== wfConnectSource) {
          const sourceId = target.dataset.id;
          const exists = currentWorkflow.edges.some(e => e.source === sourceId && e.target === wfConnectSource);
          if (!exists) {
            currentWorkflow.edges.push({ source: sourceId, target:wfConnectSource });
            renderEdges();
          }
        }
        wfConnecting = false;
        wfConnectSource = null;
        wfConnectSourcePos = null;
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
    
    // 节点拖拽（平移节点）
    el.addEventListener("mousedown", (e) => {
      if (e.target.classList.contains("wf-node-port")) return;
      e.stopPropagation();
      didDrag = false;
      const startX = e.clientX - node.x;
      const startY = e.clientY - node.y;
      
      const onMove = (ev) => {
        const nx = Math.max(0, ev.clientX - startX);
        const ny = Math.max(0, ev.clientY - startY);
        if (Math.abs(nx - node.x) > 3 || Math.abs(ny - node.y) > 3) didDrag = true;
        node.x = nx;
        node.y = ny;
        el.style.left = node.x + "px";
        el.style.top = node.y + "px";
        renderEdges();
      };
      
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
    
    canvas.appendChild(el);
  });
  
  // 渲染连线
  renderEdges();
}

// 画布平移初始化
function initCanvasPan() {
  const container = $("#wf-canvas-container");
  if (!container || container._panInit) return;
  container._panInit = true;
  
  container.addEventListener("mousedown", (e) => {
    // 只在空白区域按住左键/中键/空格+左键 时平移
    if (e.target !== container && e.target.id !== "wf-canvas" && e.target.id !== "wf-canvas-edges") return;
    if (e.button !== 0 && e.button !== 1) return;
    wfCanvasPanning = true;
    wfCanvasPanStart = { x: e.clientX - wfCanvasPan.x, y: e.clientY - wfCanvasPan.y };
    container.style.cursor = "grabbing";
    e.preventDefault();
    
    const onMove = (ev) => {
      if (!wfCanvasPanning) return;
      wfCanvasPan.x = ev.clientX - wfCanvasPanStart.x;
      wfCanvasPan.y = ev.clientY - wfCanvasPanStart.y;
      const canvas = $("#wf-canvas");
      const edgesSvg = $("#wf-canvas-edges");
      canvas.style.transform = `translate(${wfCanvasPan.x}px, ${wfCanvasPan.y}px)`;
      edgesSvg.style.transform = `translate(${wfCanvasPan.x}px, ${wfCanvasPan.y}px)`;
    };
    
    const onUp = () => {
      wfCanvasPanning = false;
      container.style.cursor = "";
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });
  
  // 滚轮缩放（可选，未来扩展）
}

// 渲染连线
let selectedEdgeIdx = -1;

function renderEdges() {
  const svg = $("#wf-canvas-edges");
  const tmpLine = svg.querySelector("#wf-temp-line");
  const defs = svg.querySelector("defs");
  svg.innerHTML = "";
  if (defs) svg.appendChild(defs);
  if (tmpLine) svg.appendChild(tmpLine);
  
  if (!currentWorkflow) return;
  
  if (!svg.querySelector("defs")) {
    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    defs.innerHTML = `<marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="var(--primary)"/></marker>`;
    svg.appendChild(defs);
  }
  
  currentWorkflow.edges.forEach((edge, idx) => {
    const sourceNode = currentWorkflow.nodes.find(n => n.id === edge.source);
    const targetNode = currentWorkflow.nodes.find(n => n.id === edge.target);
    if (!sourceNode || !targetNode) return;
    
    const x1 = sourceNode.x + 180;
    const y1 = sourceNode.y + 28;
    const x2 = targetNode.x;
    const y2 = targetNode.y + 28;
    
    const dx = Math.abs(x2 - x1);
    const cp = Math.max(60, dx * 0.4);
    const cx1 = x1 + cp;
    const cy1 = y1;
    const cx2 = x2 - cp;
    const cy2 = y2;
    
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", `M${x1},${y1} C${cx1},${cy1} ${cx2},${cy2} ${x2},${y2}`);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", idx === selectedEdgeIdx ? "#ef4444" : "var(--primary)");
    path.setAttribute("stroke-width", idx === selectedEdgeIdx ? "3" : "2");
    path.setAttribute("marker-end", "url(#arrowhead)");
    path.style.pointerEvents = "stroke";
    path.style.cursor = "pointer";
    path.setAttribute("stroke-linecap", "round");
    
    // 扩大点击区域
    const hitPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    hitPath.setAttribute("d", `M${x1},${y1} C${cx1},${cy1} ${cx2},${cy2} ${x2},${y2}`);
    hitPath.setAttribute("fill", "none");
    hitPath.setAttribute("stroke", "transparent");
    hitPath.setAttribute("stroke-width", "14");
    hitPath.style.cursor = "pointer";
    hitPath.style.pointerEvents = "stroke";
    
    const selectEdge = (e) => {
      e.stopPropagation();
      selectedEdgeIdx = idx;
      renderEdges();
      const tb = $("#wf-edge-toolbar");
      const info = $("#wf-edge-info");
      if (tb && info) {
        info.textContent = `${esc(sourceNode.label || edge.source)} → ${esc(targetNode.label || edge.target)}`;
        tb.style.display = "flex";
      }
    };
    
    path.addEventListener("click", selectEdge);
    hitPath.addEventListener("click", selectEdge);
    svg.appendChild(hitPath);
    
    svg.appendChild(path);
  });
}

function deselectEdge() {
  selectedEdgeIdx = -1;
  renderEdges();
  const tb = $("#wf-edge-toolbar");
  if (tb) tb.style.display = "none";
}

function deleteSelectedEdge() {
  if (selectedEdgeIdx >= 0 && currentWorkflow) {
    currentWorkflow.edges.splice(selectedEdgeIdx, 1);
    selectedEdgeIdx = -1;
    renderEdges();
    const tb = $("#wf-edge-toolbar");
    if (tb) tb.style.display = "none";
  }
}

// 获取节点图标
function getNodeIcon(type) {
  const icons = {
    start: "🏁", end: "🏁", llm: "🤖", kb_search: "📚", kb_index: "📥",
    classifier: "🎯", extractor: "📑", tool: "🔧", connector: "🗄️",
    condition: "🔀", variable: "📝", text_process: "✂️", aggregator: "🧮",
    code: "💻", http: "🌐", template: "📄", stop: "🛑", loop: "🔄",
    iteration: "➿", mcp_call: "🧩", memory_read: "📖", memory_write: "✏️",
    memory_clear: "🗑️", json_parse: "{ }", email: "📧", webhook: "🪝",
  };
  return icons[type] || "📦";
}

// 获取节点摘要
function getNodeSummary(node) {
  const cfg = node.config || {};
  switch (node.type) {
    case "start": return `输入: ${(cfg.input_fields || []).join(", ") || "无"}`;
    case "end": return cfg.result_template ? `模板: ${cfg.result_template.substring(0, 25)}...` : `输出: ${cfg.output_field || "output"}`;
    case "llm": return cfg.prompt ? cfg.prompt.substring(0, 30) + "..." : "未配置提示词";
    case "kb_search": return `检索: ${(cfg.query || "{{input}}").substring(0, 25)} top${cfg.top_k || 5}`;
    case "kb_index": return `入库: ${cfg.kb_id || "未选择"} ${cfg.mode || "append"}`;
    case "classifier": return `${(cfg.categories || []).length} 个类别`;
    case "extractor": return `${(cfg.fields || []).length} 个字段`;
    case "tool": return cfg.tool_name || "未配置";
    case "connector": return `查询 ${cfg.connector_id || "?"}`;
    case "condition": return `${(cfg.conditions || []).length} 个条件`;
    case "variable": return `${cfg.action || "set"} ${cfg.variable || ""}`;
    case "text_process": return `${cfg.op || "upper"} ${(cfg.input || "").substring(0, 20)}`;
    case "aggregator": return `${cfg.mode || "list"} ${(cfg.variables || []).join(",")}`;
    case "code": return cfg.language || "python";
    case "http": return `${cfg.method || "GET"} ${(cfg.url || "").substring(0, 25)}`;
    case "template": return cfg.template ? cfg.template.substring(0, 30) + "..." : "未配置模板";
    case "stop": return `输出: ${cfg.output_field || "output"}`;
    case "loop": return `循环: ${(cfg.array_variable||"").substring(0,20)} → ${cfg.item_variable||"item"}`;
    case "iteration": return `遍历: ${(cfg.array_variable||"").substring(0,20)}`;
    case "mcp_call": return `${cfg.mcp_server || "?"} / ${cfg.tool_name || "?"}`;
    case "memory_read": return `读取: ${cfg.memory_key || "?"}`;
    case "memory_write": return `写入: ${cfg.memory_key || "?"}`;
    case "memory_clear": return `清除: ${cfg.namespace || "default"}`;
    case "json_parse": return `解析 JSON`;
    case "email": return `邮件 → ${(cfg.to||"").substring(0,20)}`;
    case "webhook": return `回调 ${(cfg.url||"").substring(0,25)}`;
    default: return "";
  }
}

// 选中节点
function selectNode(nodeId) {
  selectedNode = nodeId;
  $$(".wf-node").forEach(el => el.classList.toggle("selected", el.dataset.id === nodeId));
}

// 列出当前工作流中可引用的变量
function buildVarHints() {
  if (!currentWorkflow) return "<span style='color:var(--text-muted)'>无</span>";
  const vars = new Set(["input"]);
  currentWorkflow.nodes.forEach(n => {
    vars.add(n.id + "_output");
    if (n.type === "condition") vars.add(n.config?.variable);
    if (n.type === "classifier") vars.add(n.id + "_category");
    if (n.type === "aggregator") vars.add(n.id + "_aggregated");
    (n.config?.fields || []).forEach(f => { if (f.name) vars.add(f.name); });
  });
  vars.delete(undefined);
  return Array.from(vars).slice(0, 30).map(v =>
    `<span class="ncf-var-chip" onclick="insertVarIntoInput('{{${v}}}')">{{${v}}}</span>`).join('');
}

// 把变量占位符插入当前焦点输入框
function insertVarIntoInput(placeholder) {
  const active = document.activeElement;
  if (active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA")) {
    const start = active.selectionStart || 0;
    const end = active.selectionEnd || 0;
    active.value = active.value.substring(0, start) + placeholder + active.value.substring(end);
    active.dispatchEvent(new Event("change", { bubbles: true }));
    active.focus();
  }
}

// 加载连接器选项到下拉框
async function loadConnectorSelect(connectorId) {
  try {
    const connectors = await api("/api/connectors");
    const sel = $("#wf-connector-select");
    if (!sel) return;
    sel.innerHTML = connectors.map(c =>
      `<option value="${c.id}" ${c.id === connectorId ? 'selected' : ''}>${esc(c.name)}（${esc(c.type)}）</option>`).join('')
      || `<option value="">暂无可用连接器</option>`;
  } catch (e) {
    console.error("加载连接器失败:", e);
    const sel = $("#wf-connector-select");
    if (sel) sel.innerHTML = `<option value="">加载失败</option>`;
  }
}

// 显示节点配置面板
function showNodeConfig(nodeId) {
  const node = currentWorkflow.nodes.find(n => n.id === nodeId);
  if (!node) return;
  $("#ncf-id").value = node.id;
  $("#ncf-label").value = node.label || '';
  const typeNames = {start:'开始',end:'结束',llm:'大模型',kb_search:'知识库检索',classifier:'意图分类',extractor:'参数提取',tool:'工具调用',connector:'数据连接器',condition:'条件判断',variable:'变量操作',text_process:'文本处理',aggregator:'数据聚合',code:'脚本代码',http:'HTTP请求',template:'模板渲染',stop:'提前终止',loop:'循环'};
  const typeName = typeNames[node.type] || node.type;
  $("#ncf-title").innerHTML = `${getNodeIcon(node.type)} ${node.label || node.id} <span class="ncf-tag">${typeName}</span>`;
  const cfg = node.config || {};
  let html = "";
  switch (node.type) {
    case "start":
      html += `<div class="ncf-section"><div class="ncf-group-title">输入参数</div>
        <div class="ncf-row"><label class="ncf-label">输入字段（逗号分隔）</label>
        <input class="ncf-input" value="${esc((cfg.input_fields || []).join(', '))}" onchange="updateNodeConfig('input_fields', this.value.split(',').map(s=>s.trim()).filter(Boolean))"></div>
        <div class="ncf-hint">定义工作流的输入参数，后续节点可通过 {{字段名}} 引用。</div></div>`;
      break;
    case "end":
      html += `<div class="ncf-section"><div class="ncf-group-title">输出配置</div>
        <div class="ncf-row"><label class="ncf-label">输出变量名</label>
        <input class="ncf-input" value="${esc(cfg.output_field || 'output')}" onchange="updateNodeConfig('output_field', this.value)"></div>
        <div class="ncf-row"><label class="ncf-label">输出描述</label>
        <input class="ncf-input" value="${esc(cfg.description || '')}" onchange="updateNodeConfig('description', this.value)" placeholder="描述该输出的用途"></div>
        <div class="ncf-row"><label class="ncf-label">返回结果模板（支持 {{变量}}）</label>
        <textarea class="ncf-textarea" rows="4" onchange="updateNodeConfig('result_template', this.value)" placeholder="留空则直接输出变量值，填写模板可组合多个变量">{{cfg.result_template || ''}}</textarea></div>
        <div class="ncf-hint">结果模板示例：<code>{"answer": "{{llm_1_output}}", "sources": "{{kb_results}}"}</code>。留空时直接返回 output_field 变量的值。</div></div>`;
      break;
    case "llm":
      html += `<div class="ncf-section"><div class="ncf-group-title">🤖 模型配置</div>
        <div class="ncf-row"><label class="ncf-label">模型来源</label>
        <select class="ncf-select" id="ncf-llm-source" onchange="handleLlmSourceChange(this.value)">
          <option value="cloud" ${cfg.model_source!=='local'?'selected':''}>☁ 云端模型</option>
          <option value="local" ${cfg.model_source==='local'?'selected':''}>🏠 本地模型（Ollama）</option>
        </select></div>
        <div class="ncf-row" id="ncf-llm-cloud-row" style="${cfg.model_source==='local'?'display:none':''}"><label class="ncf-label">云端模型</label>
        <div style="display:flex; gap:6px;">
          <input class="ncf-input" id="ncf-llm-model-input" value="${esc(cfg.model || '')}" onchange="updateNodeConfig('model', this.value)" placeholder="留空使用默认模型" style="flex:1;">
          <button class="btn-test" onclick="refreshCloudModels()" style="white-space:nowrap; font-size:12px;">🔄 刷新</button>
        </div>
        <div id="ncf-llm-model-list" style="margin-top:6px; display:flex; flex-wrap:wrap; gap:4px;"></div></div>
        <div class="ncf-row" id="ncf-llm-local-row" style="${cfg.model_source!=='local'?'display:none':''}"><label class="ncf-label">本地模型（Ollama）</label>
        <div style="display:flex; gap:6px;">
          <select class="ncf-select" id="ncf-ollama-select" onchange="updateNodeConfig('model', this.value)" style="flex:1;">
            <option value="">加载中...</option>
          </select>
          <button class="btn-test" onclick="loadOllamaModels()" style="white-space:nowrap; font-size:12px;">🔄 刷新</button>
        </div>
        <div id="ncf-ollama-info" style="margin-top:4px; font-size:11px; color:var(--text-muted);"></div></div></div>`;
      html += `<div class="ncf-section"><div class="ncf-group-title">📝 提示词</div>
        <div class="ncf-row"><label class="ncf-label">系统提示词</label>
        <textarea class="ncf-textarea" rows="3" onchange="updateNodeConfig('system', this.value)">${esc(cfg.system || '')}</textarea></div>
        <div class="ncf-row"><label class="ncf-label">用户提示词（支持 {{变量}}）</label>
        <textarea class="ncf-textarea" rows="4" onchange="updateNodeConfig('prompt', this.value)">${esc(cfg.prompt || '')}</textarea></div></div>`;
      html += `<div class="ncf-section"><div class="ncf-group-title">⚙ 输出 & 参数</div>
        <div class="ncf-row-inline"><div><label class="ncf-label">输出变量名</label>
        <input class="ncf-input" value="${esc(cfg.output_variable || (node.id+'_output'))}" onchange="updateNodeConfig('output_variable', this.value)"></div>
        <div><label class="ncf-label">温度 (0-2)</label>
        <input class="ncf-input" type="number" step="0.1" min="0" max="2" value="${cfg.temperature||''}" onchange="updateNodeConfig('temperature', parseFloat(this.value)||0)" placeholder="默认"></div></div>
        <div class="ncf-row-inline"><div><label class="ncf-label">最大Token</label>
        <input class="ncf-input" type="number" value="${cfg.max_tokens||''}" onchange="updateNodeConfig('max_tokens', parseInt(this.value)||null)" placeholder="不限"></div>
        <div><label class="ncf-label">记忆模式</label>
        <select class="ncf-select" onchange="updateNodeConfig('memory_mode', this.value)">
          <option value="none" ${cfg.memory_mode==='none'?'selected':''}>无</option>
          <option value="self" ${cfg.memory_mode==='self'?'selected':''}>本节点缓存</option>
          <option value="custom" ${cfg.memory_mode==='custom'?'selected':''}>自定义</option>
        </select></div></div>
        <div class="ncf-row"><label class="ncf-label"><input type="checkbox" ${cfg.retry?'checked':''} onchange="updateNodeConfig('retry', this.checked)"> 失败重试</label></div>
        ${cfg.retry?`<div class="ncf-row-inline"><div><label class="ncf-label">次数</label><input class="ncf-input" type="number" value="${cfg.max_retries||3}" onchange="updateNodeConfig('max_retries',parseInt(this.value)||3)"></div><div><label class="ncf-label">间隔(ms)</label><input class="ncf-input" type="number" value="${cfg.retry_interval||1000}" onchange="updateNodeConfig('retry_interval',parseInt(this.value)||1000)"></div></div>`:''}</div>`;
      // 延迟加载模型列表
      setTimeout(() => {
        if (cfg.model_source === 'local') loadOllamaModels();
        else refreshCloudModels();
      }, 100);
      break;
    case "kb_search":
      html += `<div class="ncf-section"><div class="ncf-group-title">知识库检索</div>
        <div class="ncf-row"><label class="ncf-label">知识库</label><select class="ncf-select" id="ncf-kb-select" onchange="updateNodeConfig('kb_id',this.value)"></select></div>
        <div class="ncf-row"><label class="ncf-label">查询（支持 {{变量}}）</label><input class="ncf-input" value="${esc(cfg.query||'{{input}}')}" onchange="updateNodeConfig('query',this.value)"></div>
        <div class="ncf-row-inline"><div><label class="ncf-label">Top K</label><input class="ncf-input" type="number" value="${cfg.top_k||5}" onchange="updateNodeConfig('top_k',parseInt(this.value)||5)"></div><div><label class="ncf-label">阈值</label><input class="ncf-input" type="number" step="0.1" value="${cfg.threshold||''}" onchange="updateNodeConfig('threshold',parseFloat(this.value)||0)" placeholder="0.5"></div></div>
        <div class="ncf-row"><label class="ncf-label">输出变量名</label><input class="ncf-input" value="${esc(cfg.output_variable||(node.id+'_results'))}" onchange="updateNodeConfig('output_variable',this.value)"></div></div>`;
      break;
    case "classifier":
      html += `<div class="ncf-section"><div class="ncf-group-title">意图分类</div>
        <div class="ncf-row"><label class="ncf-label">输入（支持 {{变量}}）</label><input class="ncf-input" value="${esc(cfg.input||'{{input}}')}" onchange="updateNodeConfig('input',this.value)"></div>
        <div class="ncf-row"><label class="ncf-label">类别（每行一个）</label><textarea class="ncf-textarea" rows="4" onchange="updateNodeConfig('categories',this.value.split(/\n/).map(s=>s.trim()).filter(Boolean))">${esc((cfg.categories||[]).join('\n'))}</textarea></div>
        <div class="ncf-row"><label class="ncf-label">模型</label><input class="ncf-input" value="${esc(cfg.model||'')}" onchange="updateNodeConfig('model',this.value)"></div></div>`;
      html += `<div class="ncf-section"><div class="ncf-group-title">路由条件</div>
        <div class="ncf-row"><label class="ncf-label">条件（JSON数组）</label><textarea class="ncf-textarea" rows="4" onchange="updateNodeConfig('conditions',JSON.parse(this.value||'[]'))" style="font-family:monospace;">${JSON.stringify(cfg.conditions||[],null,2)}</textarea></div>
        <div class="ncf-hint">分类结果存为 <b>${esc(node.id)}_category</b>。格式：[{"operator":"eq","value":"类别","target":"节点ID"}]</div></div>`;
      break;
    case "extractor":
      html += `<div class="ncf-section"><div class="ncf-group-title">参数提取</div>
        <div class="ncf-row"><label class="ncf-label">输入（支持 {{变量}}）</label><input class="ncf-input" value="${esc(cfg.input||'{{input}}')}" onchange="updateNodeConfig('input',this.value)"></div>
        <div class="ncf-row"><label class="ncf-label">字段（JSON数组）</label><textarea class="ncf-textarea" rows="5" onchange="updateNodeConfig('fields',JSON.parse(this.value||'[]'))" style="font-family:monospace;">${JSON.stringify(cfg.fields||[{name:'title',type:'string',description:'标题'}],null,2)}</textarea></div>
        <div class="ncf-row"><label class="ncf-label">模型</label><input class="ncf-input" value="${esc(cfg.model||'')}" onchange="updateNodeConfig('model',this.value)"></div></div>`;
      break;
    case "tool":
      html += `<div class="ncf-section"><div class="ncf-group-title">工具调用</div>
        <div class="ncf-row"><label class="ncf-label">工具名称</label><input class="ncf-input" value="${esc(cfg.tool_name||'')}" onchange="updateNodeConfig('tool_name',this.value)"></div>
        <div class="ncf-row"><label class="ncf-label">参数（JSON）</label><textarea class="ncf-textarea" rows="3" onchange="updateNodeConfig('arguments',JSON.parse(this.value||'{}'))" style="font-family:monospace;">${JSON.stringify(cfg.arguments||{},null,2)}</textarea></div></div>`;
      break;
    case "connector":
      html += `<div class="ncf-section"><div class="ncf-group-title">数据连接器</div>
        <div class="ncf-row"><label class="ncf-label">连接器</label><select class="ncf-select" id="ncf-connector-select" onchange="updateNodeConfig('connector_id',this.value)"></select></div>
        <div class="ncf-row"><label class="ncf-label">查询</label><textarea class="ncf-textarea" rows="3" onchange="updateNodeConfig('query',this.value)" style="font-family:monospace;">${esc(cfg.query||'')}</textarea></div></div>`;
      break;
    case "condition":
      html += `<div class="ncf-section"><div class="ncf-group-title">条件判断</div>
        <div class="ncf-row"><label class="ncf-label">变量（支持 {{变量}}）</label><input class="ncf-input" value="${esc(cfg.variable||'')}" onchange="updateNodeConfig('variable',this.value)"></div>
        <div class="ncf-row"><label class="ncf-label">条件（JSON数组）</label><textarea class="ncf-textarea" rows="5" onchange="updateNodeConfig('conditions',JSON.parse(this.value||'[]'))" style="font-family:monospace;">${JSON.stringify(cfg.conditions||[{operator:'eq',value:'',target:''}],null,2)}</textarea></div></div>`;
      break;
    case "variable":
      html += `<div class="ncf-section"><div class="ncf-group-title">变量操作</div>
        <div class="ncf-row"><label class="ncf-label">操作</label><select class="ncf-select" onchange="updateNodeConfig('action',this.value)">
          <option value="set" ${cfg.action==='set'?'selected':''}>设置</option><option value="append" ${cfg.action==='append'?'selected':''}>追加</option><option value="increment" ${cfg.action==='increment'?'selected':''}>递增</option></select></div>
        <div class="ncf-row"><label class="ncf-label">变量名</label><input class="ncf-input" value="${esc(cfg.variable||'')}" onchange="updateNodeConfig('variable',this.value)"></div>
        <div class="ncf-row"><label class="ncf-label">值（支持 {{变量}}）</label><input class="ncf-input" value="${esc(cfg.value||'')}" onchange="updateNodeConfig('value',this.value)"></div></div>`;
      break;
    case "text_process":
      html += `<div class="ncf-section"><div class="ncf-group-title">文本处理</div>
        <div class="ncf-row"><label class="ncf-label">操作</label><select class="ncf-select" onchange="updateNodeConfig('op',this.value)">
          ${Object.entries({upper:'转大写',lower:'转小写',trim:'去空格',replace:'替换',extract_regex:'正则提取',truncate:'截断',split:'分割',json_parse:'JSON解析'}).map(([k,v])=>`<option value="${k}" ${cfg.op===k?'selected':''}>${v}</option>`).join('')}</select></div>
        <div class="ncf-row"><label class="ncf-label">输入（支持 {{变量}}）</label><input class="ncf-input" value="${esc(cfg.input||'{{input}}')}" onchange="updateNodeConfig('input',this.value)"></div>
        ${cfg.op==='replace'?`<div class="ncf-row-inline"><div><label class="ncf-label">查找</label><input class="ncf-input" value="${esc(cfg.old||'')}" onchange="updateNodeConfig('old',this.value)"></div><div><label class="ncf-label">替换</label><input class="ncf-input" value="${esc(cfg.new||'')}" onchange="updateNodeConfig('new',this.value)"></div></div>`:''}
        <div class="ncf-row"><label class="ncf-label">输出变量名</label><input class="ncf-input" value="${esc(cfg.output_variable||(node.id+'_output'))}" onchange="updateNodeConfig('output_variable',this.value)"></div></div>`;
      break;
    case "aggregator":
      html += `<div class="ncf-section"><div class="ncf-group-title">数据聚合</div>
        <div class="ncf-row"><label class="ncf-label">模式</label><select class="ncf-select" onchange="updateNodeConfig('mode',this.value)"><option value="text" ${cfg.mode==='text'?'selected':''}>文本拼接</option><option value="list" ${cfg.mode==='list'?'selected':''}>列表</option><option value="json" ${cfg.mode==='json'?'selected':''}>JSON</option></select></div>
        <div class="ncf-row"><label class="ncf-label">变量（逗号分隔）</label><input class="ncf-input" value="${(cfg.variables||[]).join(', ')}" onchange="updateNodeConfig('variables',this.value.split(',').map(s=>s.trim()).filter(Boolean))"></div></div>`;
      break;
    case "code":
      html += `<div class="ncf-section"><div class="ncf-group-title">脚本代码</div>
        <div class="ncf-row-inline"><div><label class="ncf-label">语言</label><select class="ncf-select" onchange="updateNodeConfig('language',this.value)"><option value="python" ${cfg.language==='python'?'selected':''}>Python</option></select></div><div><label class="ncf-label">超时(秒)</label><input class="ncf-input" type="number" value="${cfg.timeout||30}" onchange="updateNodeConfig('timeout',parseInt(this.value)||30)"></div></div>
        <div class="ncf-row"><label class="ncf-label">代码</label><textarea class="ncf-textarea" rows="8" onchange="updateNodeConfig('code',this.value)" style="font-family:monospace;font-size:12px;">${esc(cfg.code||'# params[\"input\"] 读取输入\nresult = params.get("input", "")')}</textarea></div>
        <div class="ncf-row"><label class="ncf-label">输出变量名</label><input class="ncf-input" value="${esc(cfg.output_variable||'result')}" onchange="updateNodeConfig('output_variable',this.value)"></div></div>`;
      break;
    case "http":
      html += `<div class="ncf-section"><div class="ncf-group-title">HTTP 请求</div>
        <div class="ncf-row"><label class="ncf-label">URL</label><input class="ncf-input" value="${esc(cfg.url||'')}" onchange="updateNodeConfig('url',this.value)"></div>
        <div class="ncf-row-inline"><div><label class="ncf-label">方法</label><select class="ncf-select" onchange="updateNodeConfig('method',this.value)">${['GET','POST','PUT','DELETE'].map(m=>`<option value="${m}" ${cfg.method===m?'selected':''}>${m}</option>`).join('')}</select></div><div><label class="ncf-label">超时</label><input class="ncf-input" type="number" value="${cfg.timeout||30}" onchange="updateNodeConfig('timeout',parseInt(this.value)||30)"></div></div>
        <div class="ncf-row"><label class="ncf-label">请求头(JSON)</label><textarea class="ncf-textarea" rows="2" onchange="updateNodeConfig('headers',JSON.parse(this.value||'{}'))" style="font-family:monospace;">${JSON.stringify(cfg.headers||{},null,2)}</textarea></div>
        <div class="ncf-row"><label class="ncf-label">请求体</label><textarea class="ncf-textarea" rows="3" onchange="updateNodeConfig('body',this.value)">${esc(cfg.body||'')}</textarea></div></div>`;
      break;
    case "template":
      html += `<div class="ncf-section"><div class="ncf-group-title">模板渲染</div>
        <div class="ncf-row"><label class="ncf-label">模板（支持 {{变量}}）</label><textarea class="ncf-textarea" rows="5" onchange="updateNodeConfig('template',this.value)">${esc(cfg.template||'')}</textarea></div>
        <div class="ncf-row"><label class="ncf-label">输出变量名</label><input class="ncf-input" value="${esc(cfg.output_variable||(node.id+'_output'))}" onchange="updateNodeConfig('output_variable',this.value)"></div></div>`;
      break;
    case "stop":
      html += `<div class="ncf-section"><div class="ncf-group-title">提前终止</div>
        <div class="ncf-row"><label class="ncf-label">输出变量名</label><input class="ncf-input" value="${esc(cfg.output_field||'output')}" onchange="updateNodeConfig('output_field',this.value)"></div></div>`;
      break;
    case "loop":
      html += `<div class="ncf-section"><div class="ncf-group-title">循环配置</div>
        <div class="ncf-row"><label class="ncf-label">循环数组</label><input class="ncf-input" value="${esc(cfg.array_variable||'{{input}}')}" onchange="updateNodeConfig('array_variable',this.value)"></div>
        <div class="ncf-row-inline"><div><label class="ncf-label">项变量名</label><input class="ncf-input" value="${esc(cfg.item_variable||'item')}" onchange="updateNodeConfig('item_variable',this.value)"></div><div><label class="ncf-label">索引变量名</label><input class="ncf-input" value="${esc(cfg.index_variable||'index')}" onchange="updateNodeConfig('index_variable',this.value)"></div></div>
        <div class="ncf-row"><label class="ncf-label">最大次数</label><input class="ncf-input" type="number" value="${cfg.max_iterations||100}" onchange="updateNodeConfig('max_iterations',parseInt(this.value)||100)"></div></div>`;
      break;
    default:
      html += `<div class="ncf-section"><div class="ncf-hint">暂无特殊配置。</div></div>`;
  }
  $("#ncf-type-config").innerHTML = html;
  const vars = buildVarHints();
  $("#ncf-var-chips").innerHTML = vars || '<span style="color:var(--text-muted);font-size:12px;">暂无可用变量</span>';
  if (node.type==="connector") loadConnectorSelect(cfg.connector_id);
  if (node.type==="kb_search") loadKbSelect(cfg.kb_id);
  openModal("node-config-modal");
}

function closeNodeConfigModal() { closeModal("node-config-modal"); selectedNode = null; $$(".wf-node").forEach(el=>el.classList.remove("selected")); }

async function loadKbSelect(selected) {
  const sel = $("#ncf-kb-select"); if(!sel) return;
  try { const kbs = await api("/api/kb/list"); sel.innerHTML = '<option value="">选择知识库</option>'+kbs.map(kb=>`<option value="${kb.id}" ${kb.id===selected?'selected':''}>${esc(kb.name)}</option>`).join(''); } catch(e) { sel.innerHTML='<option value="">加载失败</option>'; }
}

// ===== LLM 模型选择 =====
function handleLlmSourceChange(source) {
  updateNodeConfig('model_source', source);
  const cloudRow = $("#ncf-llm-cloud-row");
  const localRow = $("#ncf-llm-local-row");
  if (cloudRow) cloudRow.style.display = source === 'local' ? 'none' : '';
  if (localRow) localRow.style.display = source === 'local' ? '' : 'none';
  if (source === 'local') loadOllamaModels();
  else refreshCloudModels();
}

async function loadOllamaModels() {
  const sel = $("#ncf-ollama-select");
  const info = $("#ncf-ollama-info");
  if (!sel) return;
  sel.innerHTML = '<option value="">正在扫描本地模型...</option>';
  try {
    const result = await api("/api/ollama/models");
    if (result.ok && result.models.length) {
      const node = currentWorkflow?.nodes.find(n => n.id === selectedNode);
      const currentModel = node?.config?.model || '';
      sel.innerHTML = '<option value="">选择模型</option>' +
        result.models.map(m => `<option value="${esc(m.name)}" ${m.name===currentModel?'selected':''}>${esc(m.name)} (${m.size_gb}GB · ${m.parameter_size || m.family || '未知'})</option>`).join('');
      if (info) info.textContent = `✅ 已加载 ${result.count} 个本地模型`;
    } else {
      sel.innerHTML = '<option value="">未发现本地模型</option>';
      if (info) info.innerHTML = `⚠ ${esc(result.msg || '无法连接 Ollama')}<br><span style="font-size:10px;">请确保 Ollama 已启动：<code>ollama serve</code></span>`;
    }
  } catch (e) {
    sel.innerHTML = '<option value="">连接失败</option>';
    if (info) info.textContent = '❌ ' + e.message;
  }
}

async function refreshCloudModels() {
  const list = $("#ncf-llm-model-list");
  const input = $("#ncf-llm-model-input");
  if (!list || !input) return;
  list.innerHTML = '<span style="font-size:11px; color:var(--text-muted);">加载中...</span>';
  try {
    const providers = await api("/api/providers");
    const models = [];
    providers.forEach(p => {
      (p.models || []).forEach(m => {
        models.push({ model: m, provider: p.name || p.id, isFree: (p.type || '').includes('free') || (p.pricing || {}).input === 0 });
      });
    });
    if (models.length) {
      list.innerHTML = models.slice(0, 30).map(m =>
        `<span class="ncf-var-chip" onclick="document.getElementById('ncf-llm-model-input').value='${esc(m.model)}';updateNodeConfig('model','${esc(m.model)}')">${m.isFree?'🆓':'💰'} ${esc(m.model)}</span>`
      ).join('');
    } else {
      list.innerHTML = '<span style="font-size:11px; color:var(--text-muted);">未配置供应商，请先在设置中添加</span>';
    }
  } catch (e) {
    list.innerHTML = '<span style="font-size:11px; color:#ef4444;">加载失败</span>';
  }
}


// 更新节点字段
function updateNodeField(field, value) {
  if (!selectedNode || !currentWorkflow) return;
  const node = currentWorkflow.nodes.find(n => n.id === selectedNode);
  if (!node) return;
  
  if (field === "id") {
    // 更新所有相关的edges
    const oldId = node.id;
    currentWorkflow.edges.forEach(e => {
      if (e.source === oldId) e.source = value;
      if (e.target === oldId) e.target = value;
    });
    node.id = value;
    selectedNode = value;
  } else {
    node[field] = value;
  }
  
  renderWorkflowCanvas();
  selectNode(selectedNode);
}

// 更新节点配置
function updateNodeConfig(key, value) {
  if (!selectedNode || !currentWorkflow) return;
  const node = currentWorkflow.nodes.find(n => n.id === selectedNode);
  if (!node) return;
  
  if (!node.config) node.config = {};
  node.config[key] = value;
  
  renderWorkflowCanvas();
  selectNode(selectedNode);
}

// 关闭节点配置
function closeNodeConfig() {
  closeNodeConfigModal();
  selectedNode = null;
  $$(".wf-node").forEach(el => el.classList.remove("selected"));
}

// 删除选中节点
function deleteSelectedNode() {
  if (!selectedNode || !currentWorkflow) return;
  
  const node = currentWorkflow.nodes.find(n => n.id === selectedNode);
  if (!node || node.type === "start" || node.type === "end") {
    alert("开始和结束节点不能删除");
    return;
  }
  
  if (!confirm(`确定删除节点 "${node.label || node.id}"？`)) return;
  
  currentWorkflow.nodes = currentWorkflow.nodes.filter(n => n.id !== selectedNode);
  currentWorkflow.edges = currentWorkflow.edges.filter(e => e.source !== selectedNode && e.target !== selectedNode);
  ensureBackboneEdge();
  
  closeNodeConfig();
  renderWorkflowCanvas();
}

// 节点分类定义
const WF_NODE_CATEGORIES = [
  {
    name: "流转控制", icon: "🔄",
    nodes: [
      { type: "start", icon: "🏁", label: "开始", desc: "入口" },
      { type: "end", icon: "🏁", label: "结束", desc: "出口" },
      { type: "stop", icon: "🛑", label: "直达", desc: "提前终止" },
      { type: "condition", icon: "🔀", label: "条件", desc: "分支" },
      { type: "classifier", icon: "🎯", label: "意图分类", desc: "路由" },
      { type: "loop", icon: "🔄", label: "循环", desc: "迭代" },
      { type: "iteration", icon: "➿", label: "遍历", desc: "数组" },
    ]
  },
  {
    name: "LLM", icon: "🤖",
    nodes: [
      { type: "llm", icon: "🤖", label: "LLM", desc: "对话/补全" },
      { type: "extractor", icon: "📑", label: "参数提取", desc: "结构化" },
      { type: "template", icon: "📄", label: "模板", desc: "文本渲染" },
    ]
  },
  {
    name: "知识库", icon: "📚",
    nodes: [
      { type: "kb_search", icon: "📚", label: "知识检索", desc: "RAG召回" },
      { type: "kb_index", icon: "📥", label: "知识入库", desc: "索引文档" },
    ]
  },
  {
    name: "记忆", icon: "🧠",
    nodes: [
      { type: "memory_read", icon: "📖", label: "记忆读取", desc: "上下文" },
      { type: "memory_write", icon: "✏️", label: "记忆写入", desc: "保存" },
      { type: "memory_clear", icon: "🗑️", label: "记忆清除", desc: "重置" },
    ]
  },
  {
    name: "MCP 工具", icon: "🧩",
    nodes: [
      { type: "mcp_call", icon: "🧩", label: "MCP 调用", desc: "工具/资源" },
      { type: "tool", icon: "🔧", label: "内置工具", desc: "函数调用" },
    ]
  },
  {
    name: "数据处理", icon: "📊",
    nodes: [
      { type: "variable", icon: "📝", label: "变量", desc: "读写" },
      { type: "text_process", icon: "✂️", label: "文本处理", desc: "转换" },
      { type: "aggregator", icon: "🧮", label: "聚合", desc: "合并" },
      { type: "code", icon: "💻", label: "代码", desc: "Python/JS" },
      { type: "json_parse", icon: "{ }", label: "JSON解析", desc: "结构化" },
    ]
  },
  {
    name: "外部集成", icon: "🔗",
    nodes: [
      { type: "http", icon: "🌐", label: "HTTP请求", desc: "REST/API" },
      { type: "connector", icon: "🗄️", label: "数据连接", desc: "SQL/NoSQL" },
      { type: "email", icon: "📧", label: "邮件", desc: "收发" },
      { type: "webhook", icon: "🪝", label: "Webhook", desc: "回调" },
    ]
  },
];

// 渲染左侧分类节点面板
function ensureBackboneEdge() {
  // 不再强制 start→end，允许用户自由连线 start→其他节点→end
}

function renderNodePanel() {
  const container = $("#wf-node-categories");
  if (!container) return;
  
  container.innerHTML = WF_NODE_CATEGORIES.map((cat, ci) => {
    const itemsHtml = cat.nodes.map(n => `
      <div class="wf-panel-node" data-type="${n.type}" title="${n.desc}">
        <span class="node-icon">${n.icon}</span>
        <span class="node-label">${n.label}</span>
        <span class="node-desc">${n.desc}</span>
      </div>
    `).join('');
    return `
      <div class="wf-cat-group" data-cat="${ci}">
        <div class="wf-cat-header" onclick="toggleNodeCat(${ci})">
          <span class="cat-arrow">▼</span>
          <span>${cat.icon} ${cat.name}</span>
        </div>
        <div class="wf-cat-items" id="wf-cat-items-${ci}">${itemsHtml}</div>
      </div>
    `;
  }).join('');
  
  // 为每个面板节点绑定拖拽/点击事件
  container.querySelectorAll(".wf-panel-node").forEach(el => {
    // 点击添加到画布中心
    el.addEventListener("click", () => {
      if (!currentWorkflow) return;
      addWfNode(el.dataset.type);
    });
    
    // 拖拽到画布
    el.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const type = el.dataset.type;
      const container = $("#wf-canvas-container");
      if (!container) return;
      
      // 创建拖拽预览
      const preview = document.createElement("div");
      preview.className = "wf-node";
      preview.style.position = "fixed";
      preview.style.pointerEvents = "none";
      preview.style.opacity = "0.8";
      preview.style.zIndex = "9999";
      preview.style.width = "160px";
      const cat = WF_NODE_CATEGORIES.flatMap(c => c.nodes).find(n => n.type === type);
      preview.innerHTML = `<div class="wf-node-header">${cat ? cat.icon : '📦'} ${cat ? cat.label : type}</div>`;
      document.body.appendChild(preview);
      
      const onMove = (ev) => {
        preview.style.left = (ev.clientX - 70) + "px";
        preview.style.top = (ev.clientY - 20) + "px";
      };
      
      const onUp = (ev) => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        preview.remove();
        
        // 检查是否在画布区域内松开
        const cRect = container.getBoundingClientRect();
        if (ev.clientX >= cRect.left && ev.clientX <= cRect.right &&
            ev.clientY >= cRect.top && ev.clientY <= cRect.bottom) {
          // 计算画布坐标
          const x = ev.clientX - cRect.left + container.scrollLeft - wfCanvasPan.x - 80;
          const y = ev.clientY - cRect.top + container.scrollTop - wfCanvasPan.y - 30;
          addWfNodeAt(type, Math.max(10, x), Math.max(10, y));
        }
      };
      
      onMove(e);
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  });
}

// 切换分类折叠
function toggleNodeCat(idx) {
  const items = $(`#wf-cat-items-${idx}`);
  const header = items?.previousElementSibling;
  if (items) items.classList.toggle("hidden");
  if (header) header.classList.toggle("collapsed");
}

// 在指定位置添加节点
function addWfNodeAt(type, x, y) {
  if (!currentWorkflow) return;
  const id = type + "_" + (++wfNodeCounter);
  const node = {
    id, type,
    label: type.charAt(0).toUpperCase() + type.slice(1),
    x, y,
    config: getDefaultNodeConfig(type),
  };
  currentWorkflow.nodes.push(node);
  renderWorkflowCanvas();
  selectNode(id);
}

// 添加节点
function addWfNode(type) {
  if (!currentWorkflow) return;
  
  // 放在画布可视区域中心
  const container = $("#wf-canvas-container");
  let x = 300, y = 200;
  if (container) {
    x = container.scrollLeft + container.clientWidth / 2 - 80 - wfCanvasPan.x;
    y = container.scrollTop + container.clientHeight / 2 - 40 - wfCanvasPan.y;
    x = Math.max(10, x + (Math.random() * 40 - 20));
    y = Math.max(10, y + (Math.random() * 40 - 20));
  }
  
  const id = type + "_" + (++wfNodeCounter);
  const node = {
    id,
    type,
    label: type.charAt(0).toUpperCase() + type.slice(1),
    x, y,
    config: getDefaultNodeConfig(type),
  };
  
  currentWorkflow.nodes.push(node);
  renderWorkflowCanvas();
  selectNode(id);
}

// 获取默认节点配置
function getDefaultNodeConfig(type) {
  switch (type) {
    case "start": return { input_fields: ["input"] };
    case "end": return { output_field: "output", result_template: "" };
    case "llm": return { prompt: "", model: "", model_source: "cloud", system: "", temperature: 0.7, memory_mode: "none", output_variable: "", retry: false };
    case "kb_search": return { query: "{{input}}", top_k: 5, kb_id: "", score_threshold: 0.6 };
    case "kb_index": return { kb_id: "", documents: [], mode: "append" };
    case "classifier": return { input: "{{input}}", categories: [], prompt: "", model: "" };
    case "extractor": return { input: "{{input}}", fields: [], prompt: "", model: "" };
    case "tool": return { tool_name: "", arguments: {} };
    case "connector": return { connector_id: "", query: "SELECT * FROM products LIMIT 10", limit: 50, parse_json: false };
    case "condition": return { variable: "input", conditions: [] };
    case "variable": return { action: "set", variable: "", value: "" };
    case "text_process": return { op: "upper", input: "{{input}}", old: "", new: "", pattern: "", length: 100, separator: "\n", variable: "" };
    case "aggregator": return { variables: [], mode: "text", separator: "\n" };
    case "code": return { language: "python", code: "" };
    case "http": return { url: "", method: "GET", headers: {}, body: "", timeout: 30 };
    case "template": return { template: "", output_variable: "output" };
    case "stop": return { output_field: "output" };
    case "loop": return { array_variable: "", item_variable: "item", max_iterations: 10 };
    case "iteration": return { array_variable: "", item_variable: "item" };
    case "mcp_call": return { mcp_server: "", tool_name: "", arguments: "{}" };
    case "memory_read": return { memory_key: "{{input}}", namespace: "default" };
    case "memory_write": return { memory_key: "", content: "{{input}}", namespace: "default" };
    case "memory_clear": return { namespace: "default" };
    case "json_parse": return { input: "{{input}}", schema: "" };
    case "email": return { to: "", subject: "", body: "", attachments: [] };
    case "webhook": return { url: "", method: "POST", headers: {}, body: "" };
    default: return {};
  }
}

// 保存工作流
async function saveCurrentWorkflow() {
  if (!currentWorkflow) return;
  
  currentWorkflow.name = $("#wf-name-input").value.trim() || "未命名工作流";
  currentWorkflow.description = $("#wf-desc-input").value.trim();
  
  // 确保骨干连线
  ensureBackboneEdge();
  
  // 验证：必须有 start 和 end 节点
  const hasStart = currentWorkflow.nodes.some(n => n.type === "start");
  const hasEnd = currentWorkflow.nodes.some(n => n.type === "end");
  if (!hasStart || !hasEnd) {
    alert("工作流必须包含开始和结束节点");
    return;
  }
  
  // 警告：如果没有从 start 到 end 的路径
  const startNode = currentWorkflow.nodes.find(n => n.type === "start");
  const endNode = currentWorkflow.nodes.find(n => n.type === "end");
  if (startNode && endNode) {
    const visited = new Set();
    const queue = [startNode.id];
    visited.add(startNode.id);
    let found = false;
    while (queue.length > 0) {
      const cur = queue.shift();
      if (cur === endNode.id) { found = true; break; }
      currentWorkflow.edges.forEach(e => {
        if (e.source === cur && !visited.has(e.target)) {
          visited.add(e.target);
          queue.push(e.target);
        }
      });
    }
    if (!found && !confirm("⚠ 当前没有从开始到结束的完整路径，是否仍要保存？")) {
      return;
    }
  }
  
  try {
    const result = await api("/api/workflows", {
      method: "POST",
      body: JSON.stringify(currentWorkflow),
    });
    
    if (result.ok) {
      currentWorkflow.id = result.id;
      alert("保存成功！");
    }
  } catch (e) {
    alert("保存失败: " + e.message);
  }
}

// 运行工作流
async function runWorkflow(wfId) {
  const input = prompt("请输入工作流参数（JSON格式）：", '{"input": "Hello"}');
  if (input === null) return;
  
  let inputData;
  try {
    inputData = JSON.parse(input);
  } catch (e) {
    alert("JSON格式错误");
    return;
  }
  
  const resultDiv = $("#wf-run-result");
  const outputDiv = $("#wf-run-output");
  resultDiv.style.display = "block";
  outputDiv.innerHTML = '<div style="color:var(--text-muted);">运行中...</div>';
  
  try {
    const result = await api(`/api/workflows/${wfId}/run`, {
      method: "POST",
      body: JSON.stringify({ input: inputData }),
    });
    
    if (result.success) {
      outputDiv.innerHTML = `
        <div style="margin-bottom:8px;"><b>✅ 运行成功</b></div>
        <div style="margin-bottom:8px; font-size:12px; color:var(--text-muted);">
          耗时: ${result.duration_ms}ms · Token: ${result.tokens_used}
        </div>
        <div style="background:var(--card-bg); padding:12px; border-radius:8px; border:1px solid var(--border); white-space:pre-wrap; font-size:13px;">
          ${esc(String(result.output || ""))}
        </div>`;
    } else {
      outputDiv.innerHTML = `
        <div style="margin-bottom:8px;"><b style="color:#ef4444;">❌ 运行失败</b></div>
        <div style="background:#fef2f2; padding:12px; border-radius:8px; border:1px solid #fca5a5; color:#dc2626; font-size:13px;">
          ${esc(result.error || "未知错误")}
        </div>`;
    }
  } catch (e) {
    outputDiv.innerHTML = `<div style="color:#ef4444;">运行失败: ${e.message}</div>`;
  }
}

// 运行当前编辑的工作流
async function runCurrentWorkflow() {
  if (!currentWorkflow || !currentWorkflow.id) {
    alert("请先保存工作流");
    return;
  }
  await runWorkflow(currentWorkflow.id);
}

// 删除工作流
async function deleteWorkflow(wfId) {
  if (!confirm("确定删除该工作流？")) return;
  
  try {
    await api(`/api/workflows/${wfId}`, { method: "DELETE" });
    loadWorkflowList();
  } catch (e) {
    alert("删除失败: " + e.message);
  }
}

// ===== 请求观测 =====
async function showWfObservation(wfId) {
  try {
    const execs = await api(`/api/workflows/${wfId}/executions?limit=20`);
    const wf = allWorkflows.find(w => w.id === wfId);
    const wfName = wf ? wf.name : wfId;

    if (!execs.length) {
      openModal("wf-obs-modal");
      $("#wf-obs-title").textContent = `👁 请求观测 — ${wfName}`;
      $("#wf-obs-content").innerHTML = `
        <div style="text-align:center; padding:40px 20px; color:var(--text-muted);">
          <div style="font-size:36px; margin-bottom:12px;">📭</div>
          <p>暂无执行记录</p>
        </div>`;
      return;
    }

    let html = `<div class="wf-obs-list">`;
    execs.forEach(exec => {
      const status = exec.status === "completed" ? "✅ 成功" : "❌ 失败";
      const statusClass = exec.status === "completed" ? "wf-status-ok" : "wf-status-fail";
      const timeStr = exec.started_at ? new Date(exec.started_at * 1000).toLocaleString() : "";
      const nodeReqs = exec.node_requests || {};
      const nodeCount = Object.keys(nodeReqs).length;

      html += `
        <div class="wf-obs-exec">
          <div class="wf-obs-exec-header" onclick="this.parentElement.classList.toggle('expanded')">
            <div class="wf-obs-exec-info">
              <span class="${statusClass}">${status}</span>
              <span style="color:var(--text-muted); font-size:12px;">${timeStr}</span>
              <span style="font-size:11px; color:var(--text-muted);">耗时 ${exec.duration_ms || 0}ms · ${exec.tokens_used || 0} tokens · ${nodeCount} 个节点请求</span>
            </div>
            <span class="wf-obs-arrow">▶</span>
          </div>
          <div class="wf-obs-exec-detail">`;

      // 显示输入
      html += `<div class="wf-obs-section">
        <div class="wf-obs-section-title">📥 输入</div>
        <pre class="wf-obs-code">${esc(JSON.stringify(exec.input || {}, null, 2))}</pre>
      </div>`;

      // 显示输出
      if (exec.output) {
        html += `<div class="wf-obs-section">
          <div class="wf-obs-section-title">📤 输出</div>
          <pre class="wf-obs-code">${esc(String(exec.output).substring(0, 2000))}</pre>
        </div>`;
      }

      // 显示错误
      if (exec.error) {
        html += `<div class="wf-obs-section">
          <div class="wf-obs-section-title">❌ 错误</div>
          <pre class="wf-obs-code wf-obs-error">${esc(exec.error)}</pre>
        </div>`;
      }

      // 显示各节点请求/响应
      const nodeIds = Object.keys(nodeReqs);
      if (nodeIds.length) {
        html += `<div class="wf-obs-section">
          <div class="wf-obs-section-title">🔗 节点请求详情（${nodeIds.length} 个）</div>`;
        nodeIds.forEach(nid => {
          const nr = nodeReqs[nid];
          const typeLabel = nr.type || "unknown";
          const typeColor = { llm: "#3b82f6", http: "#8b5cf6", code: "#f59e0b", connector: "#10b981", kb_search: "#06b6d4" }[typeLabel] || "#6b7280";
          html += `
            <div class="wf-obs-node">
              <div class="wf-obs-node-header">
                <span class="ncf-tag" style="background:${typeColor}20; color:${typeColor};">${typeLabel}</span>
                <span style="font-weight:600; font-size:13px;">${esc(nid)}</span>
                <span style="font-size:11px; color:var(--text-muted); margin-left:auto;">${nr.duration_ms || 0}ms</span>
              </div>
              <div class="wf-obs-node-body">
                <div class="wf-obs-node-req">
                  <div class="wf-obs-node-label">Request</div>
                  <pre class="wf-obs-code-sm">${esc(JSON.stringify(nr.request || {}, null, 2))}</pre>
                </div>
                <div class="wf-obs-node-resp">
                  <div class="wf-obs-node-label">Response</div>
                  <pre class="wf-obs-code-sm">${esc(JSON.stringify(nr.response || {}, null, 2))}</pre>
                </div>
              </div>
            </div>`;
        });
        html += `</div>`;
      }

      html += `</div></div>`;
    });
    html += `</div>`;

    openModal("wf-obs-modal");
    $("#wf-obs-title").textContent = `👁 请求观测 — ${wfName}`;
    $("#wf-obs-content").innerHTML = html;
  } catch (e) {
    alert("加载执行记录失败: " + e.message);
  }
}

// ===== 工作流测试面板（右侧内嵌） =====
let wfTestFiles = [];
let wfTestVars = [];
let testPanelOpen = false;

function toggleTestPanel() {
  const panel = $("#wf-test-panel");
  const btn = $("#wf-test-toggle-btn");
  if (!panel) return;
  testPanelOpen = !testPanelOpen;
  if (testPanelOpen) {
    panel.classList.add("open");
    if (btn) btn.textContent = "✕ 关闭测试";
    initTestPanel();
  } else {
    panel.classList.remove("open");
    if (btn) btn.textContent = "▶ 测试";
  }
}

function initTestPanel() {
  if (!currentWorkflow) return;
  wfTestFiles = [];
  wfTestVars = [];
  const fileEl = $("#wf-test-file-list");
  if (fileEl) fileEl.innerHTML = "";
  // 根据 start 节点生成输入字段
  const startNode = currentWorkflow.nodes.find(n => n.type === "start");
  const fields = (startNode?.config?.input_fields) || ["input"];
  let html = "";
  fields.forEach(f => {
    html += `<div style="margin-bottom:10px;">
      <label style="display:block; font-size:12px; font-weight:600; color:var(--text-secondary); margin-bottom:4px;">${esc(f)}</label>
      <textarea id="wf-test-field-${esc(f)}" rows="3" placeholder="输入 ${esc(f)} 的值..." style="width:100%; padding:8px; border:1px solid var(--border); border-radius:6px; font-size:13px; resize:vertical; background:var(--card-bg); color:var(--chat-text); font-family:inherit;"></textarea>
    </div>`;
  });
  const container = $("#wf-test-fields-container");
  if (container) container.innerHTML = html;
  const varsEl = $("#wf-test-vars");
  if (varsEl) varsEl.innerHTML = "";
  const statusEl = $("#wf-test-status");
  if (statusEl) statusEl.textContent = "就绪";
  // 隐藏输出区
  const outArea = $("#wf-test-output-area");
  if (outArea) outArea.style.display = "none";
}

function addTestVar() {
  const id = "var_" + Date.now();
  wfTestVars.push({ key: "", value: "" });
  renderTestVars();
}

function renderTestVars() {
  const el = $("#wf-test-vars");
  if (!el) return;
  el.innerHTML = wfTestVars.map((v, i) => `
    <div style="display:flex; gap:4px; margin-bottom:4px;">
      <input placeholder="key" value="${esc(v.key)}" onchange="wfTestVars[${i}].key=this.value" style="flex:1; padding:4px 8px; border:1px solid var(--border); border-radius:4px; font-size:11px; background:var(--card-bg); color:var(--chat-text);">
      <input placeholder="value" value="${esc(v.value)}" onchange="wfTestVars[${i}].value=this.value" style="flex:1; padding:4px 8px; border:1px solid var(--border); border-radius:4px; font-size:11px; background:var(--card-bg); color:var(--chat-text);">
      <button onclick="wfTestVars.splice(${i},1);renderTestVars()" style="padding:2px 6px; border:none; background:none; color:#ef4444; cursor:pointer; font-size:12px;">✕</button>
    </div>
  `).join('');
}

function handleWfTestFiles(files) {
  for (const f of files) { wfTestFiles.push(f); }
  renderWfTestFileList();
}

function renderWfTestFileList() {
  const el = $("#wf-test-file-list");
  if (!el) return;
  el.innerHTML = wfTestFiles.map((f, i) => {
    const isImg = f.type.startsWith('image/');
    const isAudio = f.type.startsWith('audio/');
    const isVideo = f.type.startsWith('video/');
    const icon = isImg ? '🖼️' : isAudio ? '🎵' : isVideo ? '🎬' : '📄';
    const size = f.size > 1024*1024 ? (f.size/1024/1024).toFixed(1)+'MB' : (f.size/1024).toFixed(0)+'KB';
    return `<div style="display:inline-flex;align-items:center;gap:4px;padding:3px 8px;background:var(--card-bg);border:1px solid var(--border);border-radius:5px;font-size:11px;">
      <span>${icon}</span><span style="max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(f.name)}</span>
      <span style="color:var(--text-muted);font-size:9px;">${size}</span>
      <span style="cursor:pointer;color:#ef4444;font-size:11px;" onclick="wfTestFiles.splice(${i},1);renderWfTestFileList()">✕</span>
    </div>`;
  }).join('');
}

function loadWfTestPreset(type) {
  const startNode = currentWorkflow?.nodes.find(n => n.type === "start");
  const fields = (startNode?.config?.input_fields) || ["input"];
  if (type === "hello") {
    fields.forEach(f => { const el = $(`#wf-test-field-${f}`); if (el) el.value = "Hello ABcode!"; });
  } else if (type === "json") {
    const obj = {}; fields.forEach(f => obj[f] = `示例${f}`);
    fields.forEach(f => { const el = $(`#wf-test-field-${f}`); if (el) el.value = JSON.stringify(obj, null, 2); });
  } else {
    fields.forEach(f => { const el = $(`#wf-test-field-${f}`); if (el) el.value = ""; });
  }
}

async function executeWfTest() {
  if (!currentWorkflow || !currentWorkflow.id) { alert("请先保存工作流"); return; }
  const btn = $("#wf-test-run-btn");
  const status = $("#wf-test-status");
  const outArea = $("#wf-test-output-area");
  const outContent = $("#wf-test-output-content");
  btn.disabled = true; btn.textContent = "⏳ 运行中...";
  status.textContent = "正在执行工作流...";

  // 收集输入
  const startNode = currentWorkflow.nodes.find(n => n.type === "start");
  const fields = (startNode?.config?.input_fields) || ["input"];
  const inputData = {};
  fields.forEach(f => {
    const el = $(`#wf-test-field-${f}`);
    if (el) inputData[f] = el.value;
  });
  // 加入环境变量
  const envVars = {};
  wfTestVars.forEach(v => { if (v.key) envVars[v.key] = v.value; });
  if (Object.keys(envVars).length > 0) inputData._env = envVars;

  // 读取文件为 base64
  const attachments = [];
  for (const file of wfTestFiles) {
    try {
      const reader = new FileReader();
      const content = await new Promise((resolve, reject) => {
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      attachments.push({ name: file.name, type: file.type, size: file.size, data: content });
    } catch(e) { console.error("文件读取失败:", e); }
  }

  // 显示输出区
  outArea.style.display = "block";
  outContent.innerHTML = '<div style="display:flex;align-items:center;gap:8px;padding:12px;color:var(--text-muted);"><div class="typing-indicator"><span></span><span></span><span></span></div><span style="font-size:13px;">执行中...</span></div>';

  try {
    const body = { input: inputData };
    if (attachments.length > 0) body.attachments = attachments;

    const resp = await fetch(`/api/workflows/${currentWorkflow.id}/run_stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    
    if (!resp.ok) {
      const result = await api(`/api/workflows/${currentWorkflow.id}/run`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      renderTestResult(result);
    } else {
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let streamOutput = "";
      let nodeEvents = [];
      
      outContent.innerHTML = '<div id="wf-test-stream-out" style="background:var(--card-bg);padding:10px;border-radius:6px;border:1px solid var(--border);white-space:pre-wrap;font-size:12px;line-height:1.5;min-height:40px;max-height:200px;overflow-y:auto;margin-bottom:8px;"></div><div id="wf-test-stream-nodes"></div>';
      const streamOutEl = $("#wf-test-stream-out");
      const streamNodesEl = $("#wf-test-stream-nodes");
      
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const evt = JSON.parse(line.slice(6));
            if (evt.delta) {
              streamOutput += evt.delta;
              if (streamOutEl) { streamOutEl.textContent = streamOutput; streamOutEl.scrollTop = streamOutEl.scrollHeight; }
            } else if (evt.type === "node_status" && evt.data) {
              nodeEvents.push(evt.data);
              if (streamNodesEl) {
                streamNodesEl.innerHTML = nodeEvents.map(ne => {
                  const ic = getNodeIcon(ne.type || "");
                  const co = ne.status === "completed" ? "#10b981" : ne.status === "failed" ? "#ef4444" : "#f59e0b";
                  const si = ne.status === "completed" ? "✅" : ne.status === "failed" ? "❌" : "⏳";
                  return `<div style="padding:4px 8px;margin:2px 0;border-left:3px solid ${co};font-size:11px;background:var(--card-bg);border-radius:0 4px 4px 0;">
                    ${si} ${ic} <b>${esc(ne.label || ne.node_id)}</b> ${ne.duration_ms ? ne.duration_ms+'ms' : ''}
                  </div>`;
                }).join('');
              }
            } else if (evt.done) {
              const result = { success: true, output: evt.output || streamOutput, node_results: evt.node_results || {}, duration_ms: evt.duration_ms || 0, tokens_used: evt.tokens_used || 0 };
              renderTestResult(result);
            } else if (evt.error) {
              outContent.innerHTML = `<div style="padding:10px;background:#fef2f2;border:1px solid #fca5a5;border-radius:6px;color:#dc2626;font-size:12px;">
                <div style="font-weight:600;margin-bottom:4px;">❌ 运行失败</div>
                <div style="white-space:pre-wrap;">${esc(evt.error)}</div>
              </div>`;
            }
          } catch(e) {}
        }
      }
    }
  } catch (e) {
    outContent.innerHTML = `<div style="color:#ef4444;padding:12px;font-size:12px;">运行失败: ${esc(e.message)}</div>`;
  }

  btn.disabled = false; btn.textContent = "▶ 运行测试";
  status.textContent = "完成";
}

function renderTestResult(result) {
  const outContent = $("#wf-test-output-content");
  if (!outContent || !result) return;
  if (result.success) {
    const dur = result.duration_ms || 0;
    const tokens = result.tokens_used || 0;
    let html = `<div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;">
      <span style="padding:4px 10px;background:#d1fae5;border-radius:5px;color:#047857;font-weight:600;font-size:12px;">✅ 成功</span>
      <span style="padding:4px 10px;background:var(--card-bg);border-radius:5px;font-size:11px;color:var(--text-secondary);">⏱ ${dur}ms</span>
      <span style="padding:4px 10px;background:var(--card-bg);border-radius:5px;font-size:11px;color:var(--text-secondary);">🔤 ${tokens} tok</span>
    </div>`;
    if (result.node_results && Object.keys(result.node_results).length > 0) {
      html += '<div style="margin-bottom:8px;font-size:11px;font-weight:600;color:var(--text-secondary);">节点详情</div>';
      for (const [nodeId, nr] of Object.entries(result.node_results)) {
        const wfNode = currentWorkflow?.nodes?.find(n => n.id === nodeId);
        const nodeLabel = wfNode?.label || nr.label || nodeId;
        const icon = getNodeIcon(wfNode?.type || "");
        const co = nr.error ? '#ef4444' : nr.status === 'completed' ? '#10b981' : '#f59e0b';
        const si = nr.error ? '❌' : nr.status === 'completed' ? '✅' : '⏳';
        const durMs = nr.completed_at && nr.started_at ? Math.round((nr.completed_at - nr.started_at) * 1000) : 0;
        html += `<div style="margin-bottom:6px;padding:8px;border:1px solid var(--border);border-radius:6px;border-left:3px solid ${co};">
          <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
            <span style="font-weight:600;font-size:11px;">${icon} ${esc(nodeLabel)}</span>
            <span style="font-size:10px;">${si} ${durMs}ms</span>
          </div>
          <div style="font-size:11px;color:var(--text-secondary);white-space:pre-wrap;max-height:80px;overflow-y:auto;background:var(--input-bg);padding:6px;border-radius:4px;">${esc(nr.error || String(nr.output || ""))}</div>
        </div>`;
      }
    }
    html += `<div style="margin-top:8px;font-size:11px;font-weight:600;color:var(--text-secondary);">最终输出</div>
      <div style="background:var(--card-bg);padding:10px;border-radius:6px;border:1px solid var(--border);white-space:pre-wrap;font-size:12px;line-height:1.5;max-height:200px;overflow-y:auto;margin-top:4px;">${esc(String(result.output || ""))}</div>`;
    outContent.innerHTML = html;
  } else {
    outContent.innerHTML = `<div style="padding:10px;background:#fef2f2;border:1px solid #fca5a5;border-radius:6px;color:#dc2626;font-size:12px;">
      <div style="font-weight:600;margin-bottom:4px;">❌ 运行失败</div>
      <div style="white-space:pre-wrap;">${esc(result.error || "未知错误")}</div>
    </div>`;
  }
}

// 加载执行记录
async function loadWorkflowExecutions() {
  try {
    const executions = await api("/api/workflow/executions?limit=50");
    const container = $("#wf-list-content");
    
    if (!executions.length) {
      container.innerHTML = `
        <div style="text-align:center; padding:40px 20px;">
          <div style="font-size:48px; margin-bottom:16px;">📋</div>
          <h3 style="margin:0 0 8px; color:var(--chat-text);">暂无执行记录</h3>
        </div>`;
      return;
    }
    
    container.innerHTML = executions.map(exec => {
      const status = exec.status === "completed" ? "✅" : (exec.status === "failed" ? "❌" : "⏳");
      const timeStr = exec.started_at ? new Date(exec.started_at * 1000).toLocaleString() : "";
      return `
        <div class="wf-list-item">
          <div class="wf-item-info">
            <div class="wf-item-name">${status} 执行 ${exec.id}</div>
            <div class="wf-item-desc">${exec.error ? esc(exec.error) : (exec.output || "").substring(0, 50)}</div>
            <div class="wf-item-meta">${timeStr} · ${exec.duration_ms || 0}ms · ${exec.tokens_used || 0} tokens</div>
          </div>
        </div>`;
    }).join('');
  } catch (e) {
    console.error("加载执行记录失败:", e);
  }
}

// 模板库
async function showWfTemplates() {
  switchWfView("templates");
  await loadWorkflowTemplates("all");
}

async function loadWorkflowTemplates(category) {
  try {
    const templates = await api(`/api/workflow/templates?category=${category}`);
    const container = $("#wf-templates-content");
    
    container.innerHTML = templates.map(tpl => `
      <div class="wf-template-card" onclick="useWorkflowTemplate('${tpl.id}')">
        <div class="wf-tpl-icon">${tpl.icon || "🔧"}</div>
        <div class="wf-tpl-info">
          <div class="wf-tpl-name">${esc(tpl.name)}</div>
          <div class="wf-tpl-desc">${esc(tpl.description || "")}</div>
          <div class="wf-tpl-meta">${(tpl.nodes || []).length} 个节点 · 使用 ${tpl.usage_count || 0} 次</div>
        </div>
      </div>`).join('');
  } catch (e) {
    console.error("加载模板失败:", e);
  }
}

function filterWfTemplates(category) {
  $$(".wf-tab").forEach(t => t.classList.toggle("active", t.dataset.cat === category));
  loadWorkflowTemplates(category);
}

async function useWorkflowTemplate(tplId) {
  if (!confirm("使用该模板创建工作流？")) return;
  
  try {
    const result = await api(`/api/workflow/templates/${tplId}/use`, { method: "POST" });
    if (result.ok) {
      currentWorkflow = result.workflow;
      openWorkflowEditor(result.id);
    }
  } catch (e) {
    alert("创建失败: " + e.message);
  }
}

// 拖拽添加节点
document.addEventListener("DOMContentLoaded", () => {
  // 渲染分类节点面板
  renderNodePanel();
  
  // 工作流按钮
  const wfBtn = $("#workflow-btn");
  if (wfBtn) wfBtn.onclick = openWorkflow;
});

// 启动时加载自动更新设置
loadAutoUpdateSettings();

// ===== 更新通知横幅 =====
let bannerDismissed = false;

async function checkForUpdatesOnStartup() {
  // 等待设置加载完成
  setTimeout(async () => {
    try {
      const settings = await api("/api/settings");
      const enabled = settings.auto_update_enabled !== "false";
      
      if (!enabled) return;
      
      const url = settings.update_url || "";
      if (!url) return;
      
      // 检查更新
      const r = await api(`/api/update/check?url=${encodeURIComponent(url)}`);
      
      if (r.ok && r.has_update) {
        showUpdateBanner(r.latest, r.current);
      }
    } catch (e) {
      // 静默失败
    }
  }, 2000);
}

function showUpdateBanner(latest, current) {
  if (bannerDismissed) return;
  
  const banner = $("#update-banner");
  const bannerText = $("#banner-text");
  const bannerBtn = $("#banner-update-btn");
  
  bannerText.textContent = `🚀 发现新版本 ${latest} (当前 ${current})`;
  bannerBtn.style.display = "inline-block";
  banner.style.display = "block";
}

function dismissBanner() {
  const banner = $("#update-banner");
  banner.style.display = "none";
  bannerDismissed = true;
  
  // 30分钟内不再显示
  localStorage.setItem("abcode-banner-dismissed", Date.now());
}

function showUpdateDialog() {
  // 打开设置并滚动到更新部分
  openSettings();
  setTimeout(() => {
    const updateSection = document.querySelector('.settings-section h3');
    if (updateSection) {
      updateSection.scrollIntoView({ behavior: 'smooth' });
    }
  }, 100);
  dismissBanner();
}

// 检查是否已忽略横幅
(function() {
  const dismissed = localStorage.getItem("abcode-banner-dismissed");
  if (dismissed) {
    const elapsed = Date.now() - parseInt(dismissed);
    if (elapsed < 30 * 60 * 1000) { // 30分钟内
      bannerDismissed = true;
    }
  }
})();

// ===== 工具调用卡片 =====
function createToolCard(name, args) {
  const holder = document.querySelector("#messages .msg.assistant:last-child");
  const bubble = holder?.querySelector(".bubble");
  const card = document.createElement("div");
  card.className = "tool-card";
  card.innerHTML = `
    <div class="tool-card-head" onclick="this.parentElement.classList.toggle('open')">
      <span class="tool-icon">🛠</span>
      <span class="tool-name">${esc(name)}</span>
      <span class="tool-status running">运行中…</span>
    </div>
    <div class="tool-card-body">
      <div class="label">参数</div>
      <pre>${esc(JSON.stringify(args || {}, null, 2))}</pre>
      <div class="label">结果</div>
      <pre class="tool-result"></pre>
    </div>`;
  if (bubble) {
    bubble.appendChild(card);
  } else {
    // 找不到气泡时直接追加到消息区
    $("#messages").appendChild(card);
  }
  scrollBottom();
  return card;
}

function setToolStatus(card, status, text) {
  const head = card.querySelector(".tool-status");
  head.textContent = text || status;
  head.className = "tool-status " + status;
  const resultPre = card.querySelector(".tool-result");
  if (resultPre && text && status !== "running") {
    resultPre.textContent = text;
  }
  card.classList.remove("open");
  scrollBottom();
}

async function sendMessage() {
  const input = $("#chat-input");
  const text = input.value.trim();
  const hasAttach = pendingAttachments.length > 0;
  if ((!text && !hasAttach) || state.streaming) return;
  if (!state.currentConvId) {
    const data = await api("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ title: text.slice(0, 30) || "新对话", model: state.currentModel }),
    });
    state.currentConvId = data.id;
    await loadConvs();
    selectConv(data.id);
  }

  // 上传附件
  let attachments = [];
  if (hasAttach) {
    attachments = await uploadAttachments();
  }

  // 获取历史
  const history = await api(`/api/conversations/${state.currentConvId}/messages`);
  const hist = history.map((m) => ({ role: m.role, content: m.content }));

  appendMessage("user", text || "(附件)");
  if (attachments.length) {
    // 在用户气泡里显示附件
    const lastBubble = document.querySelector("#messages .msg.user:last-child .bubble");
    attachments.forEach((att) => {
      const img = document.createElement("img");
      img.className = "msg-img";
      img.src = `/uploads/${att.filename}`;
      lastBubble.appendChild(img);
    });
  }
  input.value = "";
  autoResize();

  state.streaming = true;
  $("#send-btn").style.display = "none";
  $("#stop-btn").style.display = "block";

  // 显示流式输出指示器
  const indicator = $("#streaming-indicator");
  const indicatorText = $("#streaming-text");
  indicator.classList.add("visible");
  indicatorText.textContent = "正在思考...";

  let acc = "";
  const holder = document.createElement("div");
  holder.className = "msg assistant streaming";
  holder.innerHTML = `<div class="avatar">AB</div><div class="bubble"></div>`;
  $("#messages").appendChild(holder);

  const controller = new AbortController();
  $("#stop-btn").onclick = () => controller.abort();

  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conv_id: state.currentConvId,
        provider_id: state.currentProviderId,
        model: state.currentModel,
        message: text,
        history: hist,
        attachments: attachments,
        kb_enabled: state.tbKb,
        skills_enabled: state.tbSkills,
        mcp_enabled: state.tbMcp,
        thinking_mode: state.tbThinking,
      }),
      signal: controller.signal,
    });
    if (!resp.ok) {
      const t = await resp.text();
      throw new Error(t);
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let done = false;
    let currentTool = null;
    while (true) {
      const { value, done: rd } = await reader.read();
      if (rd) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const payload = JSON.parse(line.slice(6));
        if (payload.delta) {
          acc += payload.delta;
          // 收到内容后切换为"正在生成"
          if (indicatorText.textContent !== "正在生成...") {
            indicatorText.textContent = "正在生成...";
          }
          holder.querySelector(".bubble").innerHTML = renderMarkdown(acc);
          decorateCodeBlocks(holder.querySelector(".bubble"));
          scrollBottom();
        } else if (payload.tool_start) {
          currentTool = createToolCard(payload.tool_start.name, payload.tool_start.args);
        } else if (payload.tool_result) {
          if (currentTool) {
            setToolStatus(currentTool, payload.tool_result.ok ? "ok" : "err",
              payload.tool_result.ok ? "✅ 完成" : "❌ 失败");
          }
        } else if (payload.error) {
          holder.querySelector(".bubble").innerHTML = `<div class="bubble error">⚠ ${esc(payload.error)}</div>`;
          done = true;
        } else if (payload.done) {
          done = true;
        }
      }
      if (done) break;
    }
  } catch (e) {
    if (e.name === "AbortError") {
      holder.querySelector(".bubble").innerHTML = renderMarkdown(acc + "\n\n⏹ 已停止生成");
    } else {
      holder.querySelector(".bubble").innerHTML = `<div class="bubble error">⚠ ${esc(e.message)}</div>`;
    }
  } finally {
    state.streaming = false;
    holder.classList.remove("streaming");
    indicator.classList.remove("visible");
    $("#send-btn").style.display = "block";
    $("#stop-btn").style.display = "none";
    loadConvs();
    // 生成提示词建议
    if (state.suggestionEnabled && acc && !acc.includes("⚠")) {
      const suggestions = generateSuggestions(userMsg, acc);
      renderSuggestions(suggestions, "chat-area");
    }
    if (state.currentConvId) loadMessages(state.currentConvId);
    scrollBottom();
  }
}

// ===== 事件绑定 =====
function bindEvents() {
  $("#new-chat-btn").onclick = newChat;
  $("#settings-btn").onclick = openSettings;
  $("#kb-btn").onclick = openKb;
  $("#cron-btn").onclick = openCron;
  $("#channel-btn").onclick = openChannelModal;
  $("#tools-btn").onclick = openTools;
  $("#convtools-btn").onclick = openConvTools;
  $("#team-btn").onclick = () => {
    openModal("team-modal");
    loadTeamMembers();
    loadTeamActivity();
    loadSharedConversations();
  };
  $("#expert-btn").onclick = () => {
    openModal("expert-modal");
    loadExperts();
  };
  $("#add-provider-btn").onclick = () => openProviderModal("");
  $("#send-btn").onclick = sendMessage;
  $("#attach-btn").onclick = openAttach;
  $("#voice-btn").onclick = toggleVoice;
  $("#file-input").onchange = (e) => { handleFiles(e.target.files); e.target.value = ""; };
  $("#mcp-transport").onchange = mcpFormVisible;
  $("#agent-switch").onchange = (e) => { state.agentEnabled = e.target.checked; };

  const input = $("#chat-input");
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  input.addEventListener("input", autoResize);

  $("#provider-select").onchange = (e) => {
    state.currentProviderId = e.target.value;
    const p = getProvider(state.currentProviderId);
    state.currentModel = (p && p.models.length) ? p.models[0] : (p ? p.default_model : "");
    updateModelSelect();
  };
  $("#model-select").onchange = (e) => { state.currentModel = e.target.value; };

  // 团队协作标签切换
  $$(".team-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$(".team-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const tabName = tab.dataset.tab;
      $$(".team-tab-panel").forEach((p) => (p.style.display = "none"));
      $(`#team-${tabName}-tab`).style.display = "block";
      if (tabName === "members") loadTeamMembers();
      else if (tabName === "shared") loadSharedConversations();
      else if (tabName === "activity") loadTeamActivity();
    });
  });

  // 专家套件分类切换
  $$(".expert-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$(".expert-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      loadExperts(tab.dataset.category);
      $("#expert-detail").style.display = "none";
    });
  });

  // 预设模板
  $$(".preset").forEach((btn) => {
    btn.onclick = () => {
      openProviderModal("");
      $("#pf-name").value = btn.dataset.name;
      $("#pf-url").value = btn.dataset.url;
      $("#pf-key").value = btn.dataset.key;
      if (btn.dataset.models) {
        $("#pf-models").value = btn.dataset.models;
      }
      if (btn.dataset.ctx) {
        $("#pf-context").value = btn.dataset.ctx;
      }
      // 显示免费模型信息
      const info = $("#preset-info");
      if (btn.dataset.free) {
        info.style.display = "block";
        info.innerHTML = `✨ <b>${btn.dataset.name}</b> 免费模型: <code>${btn.dataset.free}</code><br>上下文长度: ${btn.dataset.ctx ? (parseInt(btn.dataset.ctx)/1000).toFixed(0) + "K" : "未设置"}`;
      } else {
        info.style.display = "none";
      }
      $("#pf-models").focus();
    };
  });

  // 知识库快捷引用
  $("#kb-ref-btn").onclick = openKbRef;
  $("#kb-ref-close").onclick = closeKbRef;
  $("#kb-ref-input").addEventListener("input", (e) => {
    clearTimeout(kbRefTimer);
    kbRefTimer = setTimeout(() => searchKbRef(e.target.value), 300);
  });
  // Ctrl+K 快捷键打开知识库引用
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "k") {
      e.preventDefault();
      openKbRef();
    }
    if (e.key === "Escape" && $("#kb-ref-panel").style.display !== "none") {
      closeKbRef();
    }
  });

  // 工具栏开关
  $$(".tb-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      btn.classList.toggle("active");
      const tb = btn.dataset.tb;
      if (tb === "kb") state.tbKb = btn.classList.contains("active");
      else if (tb === "skills") state.tbSkills = btn.classList.contains("active");
      else if (tb === "mcp") state.tbMcp = btn.classList.contains("active");
      else if (tb === "thinking") state.tbThinking = btn.classList.contains("active");
    });
  });

  // 主题切换
  $$(".theme-btn").forEach((btn) => {
    btn.addEventListener("click", () => applyTheme(btn.dataset.theme));
  });

  // 字体设置
  const fontFamily = document.getElementById("font-family-select");
  const fontSizeDisplay = document.getElementById("font-size-display");
  const lineHeight = document.getElementById("line-height-select");
  if (fontFamily) {
    fontFamily.value = state.chatFont;
    fontFamily.addEventListener("change", () => {
      state.chatFont = fontFamily.value;
      saveFontSettings();
    });
  }
  if (fontSizeDisplay) {
    fontSizeDisplay.textContent = state.chatFontSize;
  }
  if (lineHeight) {
    lineHeight.value = state.chatLineHeight;
    lineHeight.addEventListener("change", () => {
      state.chatLineHeight = lineHeight.value;
      saveFontSettings();
    });
  }

  // 提示词建议设置
  const suggestionToggle = document.getElementById("suggestion-toggle");
  if (suggestionToggle) {
    suggestionToggle.checked = state.suggestionEnabled;
    suggestionToggle.addEventListener("change", () => {
      state.suggestionEnabled = suggestionToggle.checked;
      saveSuggestionSettings();
    });
  }

  // Agent 模式设置
  const agentSwitchPref = document.getElementById("agent-switch-pref");
  if (agentSwitchPref) {
    agentSwitchPref.checked = state.agentEnabled;
    agentSwitchPref.addEventListener("change", () => {
      state.agentEnabled = agentSwitchPref.checked;
      // 同步顶栏开关
      const agentSwitch = document.getElementById("agent-switch");
      if (agentSwitch) agentSwitch.checked = state.agentEnabled;
    });
  }

  // 主题选择器（偏好设置内）
  $$(".theme-pick-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      applyTheme(btn.dataset.theme);
      $$(".theme-pick-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
    });
  });

  // 点击遮罩关闭
  $$(".modal").forEach((m) => {
    m.addEventListener("click", (e) => {
      if (e.target === m) m.style.display = "none";
    });
  });

  initSpeech();
  loadVersion();
  
  // 启动时检查更新
  checkForUpdatesOnStartup();
}

function autoResize() {
  const input = $("#chat-input");
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
}

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

init();
