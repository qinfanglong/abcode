/* ABcode 前端逻辑 v0.3.0 */
let state = {
  convs: [],
  currentConvId: null,
  providers: [],
  currentProviderId: "",
  currentModel: "",
  streaming: false,
  abortController: null,
  editingProviderId: null,
  agentEnabled: true,
  modelTypeFilter: "all", // "all" | "local" | "network"
  theme: localStorage.getItem("abcode-theme") || "light",
  particleAnimate: localStorage.getItem("abcode-particle-anim") !== "false", // 粒子动画开关
  // 字体设置
  chatFont: localStorage.getItem("abcode-font") || '"PingFang SC", "Microsoft YaHei", "Hiragino Sans GB", sans-serif',
  chatFontSize: parseInt(localStorage.getItem("abcode-fontsize")) || 15,
  chatLineHeight: localStorage.getItem("abcode-lineheight") || "1.7",
  // 提示词建议
  suggestionEnabled: localStorage.getItem("abcode-suggestion") !== "false",
  // 工具栏开关
  tbKb: true,
  chatKbId: localStorage.getItem("abcode-chat-kb") || "",
  tbSkills: true,
  tbMcp: true,
  tbThinking: false,
  // 界面偏好（语言/时区）
  lang: localStorage.getItem("abcode-lang") || "zh-CN",
  timezone: localStorage.getItem("abcode-timezone") || "",
};

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

// 统一时间格式化：若设置了时区则按该时区显示
function fmtTime(ts, withDate = true) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  if (state.timezone) {
    try {
      const opts = withDate
        ? { timeZone: state.timezone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }
        : { timeZone: state.timezone, year: "numeric", month: "2-digit", day: "2-digit" };
      return new Intl.DateTimeFormat("zh-CN", opts).format(d);
    } catch (e) { /* 无效时区则回退 */ }
  }
  return withDate ? d.toLocaleString() : d.toLocaleDateString();
}

// ===== 初始化 =====
async function init() {
  applyTheme(state.theme);
  applyFontSettings();
  applySuggestionSettings();
  applyParticleAnimationSettings();
  await Promise.all([loadProviders(), loadConvs()]);
  bindEvents();
  loadChatKbSelect();
  // 首次加载失败时重试（后端可能尚未就绪；占位符也算失败）
  setTimeout(() => {
    const sel = $("#chat-kb-select");
    if (sel && sel.options.length < 2) loadChatKbSelect();
  }, 3000);
  if (state.providers.length > 0) {
    // 优先恢复上次选择的供应商/模型
    const savedPid = localStorage.getItem("abcode-provider");
    const savedModel = localStorage.getItem("abcode-model");
    let pid = savedPid && state.providers.find(p => p.id === savedPid) ? savedPid : "";
    // 否则优先本地 Ollama（无 Key 即可用），避免默认落在需要 Key 的网络模型上
    if (!pid) {
      const local = state.providers.find(p => isLocalProvider(p));
      pid = local ? local.id : state.providers[0].id;
    }
    state.currentProviderId = pid;
    updateProviderSelect();
    const p = getProvider(state.currentProviderId);
    let m = savedModel && p && (p.models || []).includes(savedModel) ? savedModel : "";
    if (!m && p && p.models.length) {
      // 默认优先免费模型（模型名含 free / flash / mini / lite），避免落在付费模型上
      m = p.models.find(x => /free/i.test(x)) || p.models.find(x => /flash|mini|lite|tiny|small/i.test(x)) || p.models[0];
    }
    if (!m && p && p.default_model) m = p.default_model;
    state.currentModel = m;
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
  state.particleAnimate = true;
  localStorage.removeItem("abcode-theme");
  localStorage.removeItem("abcode-font");
  localStorage.removeItem("abcode-fontsize");
  localStorage.removeItem("abcode-lineheight");
  localStorage.removeItem("abcode-suggestion");
  localStorage.removeItem("abcode-particle-anim");
  applyTheme(state.theme);
  applyFontSettings();
  applySuggestionSettings();
  applyParticleAnimationSettings();
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

// ===== 动效动画设置（粒子 / 海浪共用开关） =====
function applyParticleAnimationSettings() {
  const toggle = document.getElementById("particle-animate-toggle");
  if (toggle) toggle.checked = state.particleAnimate;
}

function saveParticleAnimationSettings() {
  localStorage.setItem("abcode-particle-anim", state.particleAnimate);
  // 当前是动效主题则立即按新状态刷新（开=动起来，关=定格静态）
  if (state.theme === "particles") startParticles({ light: false });
  else if (state.theme === "particles-light") startParticles({ light: true });
  else if (state.theme === "wave") startWaves();
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
        <div class="team-member-email">${fmtTime(a.created_at)}</div>
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

// ===== 智能体 =====
let currentAgentId = null;
let agentEditing = null;
const agentCats = [
  ["coding", "编程"], ["research", "研究"], ["analysis", "分析"],
  ["product", "产品"], ["writing", "写作"], ["security", "安全"], ["language", "语言"]
];

let _agentSource = 'created';
let _agentPage = 1;
let _agentTotalPages = 1;
const AGENT_PAGE_SIZE = 20;

async function loadAgents(source, page) {
  if (source === 'builtin' || source === 'created') _agentSource = source;
  if (page) _agentPage = page;
  const all = await api("/api/agents");
  const list = all.filter(a => _agentSource === 'builtin' ? a.is_builtin : !a.is_builtin);
  _agentTotalPages = Math.max(1, Math.ceil(list.length / AGENT_PAGE_SIZE));
  if (_agentPage > _agentTotalPages) _agentPage = _agentTotalPages;
  const start = (_agentPage - 1) * AGENT_PAGE_SIZE;
  const pageItems = list.slice(start, start + AGENT_PAGE_SIZE);
  const el = $("#agent-list");
  el.innerHTML = pageItems.map(a => `
    <div class="agent-list-item ${currentAgentId === a.id ? 'active' : ''}" data-aid="${a.id}" onclick="showAgentDetail('${a.id}')">
      <span class="agent-list-icon">${a.icon || '🤖'}</span>
      <div style="flex:1; min-width:0;">
        <div style="font-weight:600; font-size:13px;">${esc(a.name)}</div>
        <div style="font-size:11px; color:var(--text-secondary); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${esc(a.description || '')}</div>
      </div>
      ${a.is_builtin ? '<span style="font-size:10px; background:var(--input-bg); padding:2px 6px; border-radius:4px; color:var(--text-muted);">内置</span>' : ''}
    </div>
  `).join('') || '<div style="padding:20px; text-align:center; color:var(--text-muted);">暂无智能体</div>';
  // 分页条
  const pg = $("#agent-pagination");
  if (pg) {
    pg.style.display = _agentTotalPages > 1 ? 'flex' : 'none';
    const info = $("#agent-page-info");
    if (info) info.textContent = `${_agentPage}/${_agentTotalPages}`;
  }
}

function agentPage(delta) {
  const next = Math.min(Math.max(1, _agentPage + delta), _agentTotalPages);
  if (next !== _agentPage) loadAgents(null, next);
}

async function showAgentDetail(aid) {
  const a = await api(`/api/agents/${aid}`);
  currentAgentId = aid;
  // 高亮当前
  $$("#agent-list .agent-list-item").forEach(el => el.classList.toggle("active", el.dataset.aid === aid));
  const panel = $("#agent-detail-panel");
  const tools = (a.builtin_tools || []).map(t => `<span class="expert-tool-tag">${esc(t)}</span>`).join('') || '<span class="expert-tool-tag">无</span>';
  const meta = await ensureAgentBindMeta();
  const skills = (a.skill_ids || []).map(sid => `<span class="expert-tool-tag">🧩 ${esc(bindName(meta.skills, sid))}</span>`).join('') || '<span class="expert-tool-tag">无</span>';
  const kb = (a.kb_ids || []).length ? (a.kb_ids || []).map(k => `<span class="expert-tool-tag">📚 ${esc(bindName(meta.kbs, k))}</span>`).join('') : '<span class="expert-tool-tag">未绑定</span>';
  const mcp = (a.mcp_ids || []).length ? (a.mcp_ids || []).map(m => `<span class="expert-tool-tag">🔌 ${esc(bindName(meta.mcps, m))}</span>`).join('') : '<span class="expert-tool-tag">无</span>';
  const wf = a.workflow_id ? `<span class="expert-tool-tag">⚙️ ${esc(bindName(meta.wfs, a.workflow_id))}</span>` : '<span class="expert-tool-tag">未绑定</span>';
  const subs = (a.sub_agents || []).length ? a.sub_agents.join(', ') : '无';
  panel.innerHTML = `
    <div style="display:flex; align-items:center; gap:14px; margin-bottom:16px;">
      <span style="font-size:42px;">${a.icon || '🤖'}</span>
      <div style="flex:1;">
        <h3 style="margin:0; font-size:18px;">${esc(a.name)}</h3>
        <p style="margin:4px 0 0; color:var(--text-secondary); font-size:13px;">${esc(a.description || '')}</p>
      </div>
      <div style="display:flex; gap:6px;">
        <button class="btn-save" onclick="openAgentChat('${a.id}')">💬 对话</button>
        ${a.is_builtin
          ? `<button class="btn-test" onclick="openAgentFormCopy('${a.id}')">📋 复制</button>`
          : `<button class="btn-test" onclick="openAgentForm('${a.id}')">✏️ 编辑</button>`}
      </div>
    </div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
      <div class="agent-info-card">
        <div class="agent-info-label">分类</div><div>${a.category}</div>
        <div class="agent-info-label">模型偏好</div><div>${esc(a.model_preference || '自动选择')}</div>
        <div class="agent-info-label">温度</div><div>${a.temperature}</div>
      </div>
      <div class="agent-info-card">
        <div class="agent-info-label">可用工具</div><div>${tools}</div>
        <div class="agent-info-label">技能</div><div>${skills}</div>
        <div class="agent-info-label">知识库</div><div>${kb}</div>
        <div class="agent-info-label">MCP</div><div>${mcp}</div>
        <div class="agent-info-label">绑定工作流</div><div>${wf}</div>
        <div class="agent-info-label">子Agent</div><div>${esc(subs)}</div>
      </div>
    </div>
    <div style="margin-top:14px;">
      <label style="font-size:12px; font-weight:600; color:var(--text-secondary);">系统提示词</label>
      <div style="margin-top:6px; background:var(--input-bg); border:1px solid var(--border); border-radius:8px; padding:12px; font-size:13px; white-space:pre-wrap; max-height:180px; overflow-y:auto;">${esc(a.system_prompt || '（默认）')}</div>
    </div>
    <div style="margin-top:14px; display:flex; gap:8px; flex-wrap:wrap;">
      <button class="btn-test" onclick="runAgentTest('${a.id}')">▶ 运行测试</button>
      <button class="btn-test" onclick="viewAgentMemory('${a.id}')">🧠 记忆</button>
      ${a.is_builtin ? '' : `<button class="btn-test" style="color:#ef4444; border-color:#fecaca;" onclick="deleteAgent('${a.id}')">🗑 删除</button>`}
    </div>
  `;
}

async function openAgentChat(aid) {
  const a = await api(`/api/agents/${aid}`);
  closeModal("agent-modal");
  // 新建会话并切换模型
  const data = await api("/api/conversations", {
    method: "POST",
    body: JSON.stringify({ title: a.name + " 对话", model: "" })
  });
  state.currentConvId = data.id;
  await loadConvs();
  selectConv(data.id);
  // 设置会话工具和专家绑定
  try {
    await api(`/api/conversations/${data.id}/tools`, {
      method: "PUT",
      body: { expert_id: "", skill_ids: a.skill_ids || [], mcp_ids: a.mcp_ids || [], connector_ids: a.connector_ids || [] }
    });
  } catch (e) {}
  // 发送初始消息
  const input = $("#chat-input");
  input.value = `（智能体 ${a.name} 已就绪）`;
  input.value = "";
  // 在会话中标记
  const holder = document.createElement("div");
  holder.className = "msg assistant";
  holder.innerHTML = `<div class="avatar">${a.icon || '🤖'}</div><div class="bubble">🤖 已切换到智能体 <b>${esc(a.name)}</b>。当前会话将使用该智能体的系统提示词与工具配置，直接输入你的需求开始。</div>`;
  $("#messages").appendChild(holder);
  $("#welcome").style.display = "none";
  scrollBottom();
  // 保存智能体绑定到会话
  localStorage.setItem("abcode-conv-agent", data.id + "|" + aid);
  window._currentAgentCfg = a;
}

function agentFormTemplate(a, meta) {
  a = a || {};
  meta = meta || { skills: [], kbs: [], mcps: [], wfs: [] };
  const catOptions = agentCats.map(([v, label]) => `<option value="${v}" ${a.category === v ? 'selected' : ''}>${label}</option>`).join('');
  const defaultTools = ["web_search", "file_read"];
  const initTools = a.id ? (a.builtin_tools || []) : (a.builtin_tools && a.builtin_tools.length ? a.builtin_tools : defaultTools);
  const toolChecks = (window._agentToolNames || ["shell","file_read","file_write","list_files","web_search","fetch_url"]).map(t =>
    `<label style="display:inline-flex; align-items:center; gap:4px; margin:4px 8px 4px 0; font-size:12px;">
      <input type="checkbox" class="agt-tool-cb" value="${t}" ${initTools.includes(t) ? 'checked' : ''}> ${t}
    </label>`).join('');
  
  // 技能多选
  const skillChecks = (meta.skills || []).map(s =>
    `<label style="display:inline-flex; align-items:center; gap:4px; margin:4px 8px 4px 0; font-size:12px;">
      <input type="checkbox" class="agt-skill-cb" value="${s.id}" ${(a.skill_ids || []).includes(s.id) ? 'checked' : ''}> ${esc(s.name || s.id)}${s.enabled === 0 ? '（停用）' : ''}
    </label>`).join('') || '<span style="font-size:12px; color:var(--text-muted);">暂无技能（可在「技能」页创建）</span>';
  // 知识库多选
  const kbChecks = (meta.kbs || []).map(k =>
    `<label style="display:inline-flex; align-items:center; gap:4px; margin:4px 8px 4px 0; font-size:12px;">
      <input type="checkbox" class="agt-kb-cb" value="${k.id}" ${(a.kb_ids || []).includes(k.id) ? 'checked' : ''}> ${esc(k.name || k.id)}<span style="color:var(--text-muted);">(${k.doc_count || 0} 文档)</span>
    </label>`).join('') || '<span style="font-size:12px; color:var(--text-muted);">暂无知识库</span>';
  // MCP 多选
  const mcpChecks = (meta.mcps || []).map(m =>
    `<label style="display:inline-flex; align-items:center; gap:4px; margin:4px 8px 4px 0; font-size:12px;">
      <input type="checkbox" class="agt-mcp-cb" value="${m.id}" ${(a.mcp_ids || []).includes(m.id) ? 'checked' : ''}> ${esc(m.name || m.id)}
    </label>`).join('') || '<span style="font-size:12px; color:var(--text-muted);">暂无 MCP 服务器</span>';
  // 工作流下拉
  const wfOptions = '<option value="">不绑定</option>' + (meta.wfs || []).map(w =>
    `<option value="${w.id}" ${a.workflow_id === w.id ? 'selected' : ''}>${esc(w.name || w.id)}</option>`).join('');
  
  // 构建模型下拉列表（分组：本地/网络）
  const allProviders = state.providers || [];
  const localProviders = allProviders.filter(p => isLocalProvider(p));
  const networkProviders = allProviders.filter(p => !isLocalProvider(p));
  let modelOptions = '<option value="">留空=自动</option>';
  if (localProviders.length > 0) {
    modelOptions += '<optgroup label="🏠 本地模型">';
    localProviders.forEach(p => {
      (p.models || []).forEach(m => {
        const selected = a.model_preference === m ? 'selected' : '';
        modelOptions += `<option value="${m}" ${selected}>${m} (${p.name})</option>`;
      });
    });
    modelOptions += '</optgroup>';
  }
  if (networkProviders.length > 0) {
    modelOptions += '<optgroup label="☁️ 网络模型">';
    networkProviders.forEach(p => {
      (p.models || []).forEach(m => {
        const selected = a.model_preference === m ? 'selected' : '';
        const needKey = !/free/i.test(m) ? ' 🔑' : '';
        modelOptions += `<option value="${m}" ${selected}>${m}${needKey} (${p.name})</option>`;
      });
    });
    modelOptions += '</optgroup>';
  }
  
  return `
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:14px;">
      <h3 style="margin:0; font-size:16px;">${a.id ? '✏️ 编辑智能体' : '＋ 新建智能体'}</h3>
    </div>
    <input type="hidden" id="agt-id" value="${a.id || ''}">
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
      <div><label class="agent-info-label">名称 *</label><input id="agt-name" class="ncf-input" value="${esc(a.name || '')}" placeholder="智能体名称"></div>
      <div><label class="agent-info-label">图标</label><input id="agt-icon" class="ncf-input" value="${esc(a.icon || '🤖')}"></div>
    </div>
    <div style="margin-top:10px;"><label class="agent-info-label">描述</label><input id="agt-desc" class="ncf-input" value="${esc(a.description || '')}" placeholder="一句话描述"></div>
    <div style="margin-top:10px;"><label class="agent-info-label">分类</label><select id="agt-category" class="ncf-input">${catOptions}<option value="general" ${!a.category || a.category === 'general' ? 'selected' : ''}>通用</option></select></div>
    <div style="margin-top:10px;"><label class="agent-info-label">系统提示词</label><textarea id="agt-prompt" class="ncf-input" rows="5" placeholder="定义智能体的角色、能力、工作流程...">${esc(a.system_prompt || '')}</textarea></div>
    <div style="margin-top:10px;"><label class="agent-info-label">内置工具</label><div style="border:1px solid var(--border); border-radius:8px; padding:8px; margin-top:4px;">${toolChecks}</div></div>
    <div style="margin-top:10px;"><label class="agent-info-label">🧩 技能（可多选）</label><div style="border:1px solid var(--border); border-radius:8px; padding:8px; margin-top:4px;">${skillChecks}</div></div>
    <div style="margin-top:10px;"><label class="agent-info-label">📚 知识库（可多选）</label><div style="border:1px solid var(--border); border-radius:8px; padding:8px; margin-top:4px;">${kbChecks}</div></div>
    <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; margin-top:10px;">
      <div><label class="agent-info-label">知识库检索条数</label><input id="agt-kb-topk" class="ncf-input" type="number" min="1" max="20" value="${a.kb_top_k ?? 5}"></div>
      <div><label class="agent-info-label">相关度阈值</label><input id="agt-kb-threshold" class="ncf-input" type="number" step="0.05" min="0" max="1" value="${a.kb_score_threshold ?? 0.5}"></div>
      <div style="display:flex; align-items:flex-end; padding-bottom:6px;">
        <label style="display:flex; align-items:center; gap:4px; font-size:12px;"><input type="checkbox" id="agt-show-sources" ${a.show_sources !== false ? 'checked' : ''}> 回答显示来源</label>
      </div>
    </div>
    <div style="margin-top:10px;"><label class="agent-info-label">🔌 MCP 服务器（可多选）</label><div style="border:1px solid var(--border); border-radius:8px; padding:8px; margin-top:4px;">${mcpChecks}</div></div>
    <div style="margin-top:10px;"><label class="agent-info-label">⚙️ 绑定工作流</label><select id="agt-workflow" class="ncf-input">${wfOptions}</select></div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:10px;">
      <div><label class="agent-info-label">模型偏好（可选）</label><select id="agt-model" class="ncf-input" style="max-height:120px;">${modelOptions}</select></div>
      <div><label class="agent-info-label">温度</label><input id="agt-temp" class="ncf-input" type="number" step="0.1" min="0" max="2" value="${a.temperature ?? 0.7}"></div>
    </div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:10px;">
      <div><label class="agent-info-label">最大上下文</label><input id="agt-ctx" class="ncf-input" type="number" value="${a.max_context || 128000}"></div>
      <div><label class="agent-info-label">最大轮数</label><input id="agt-rounds" class="ncf-input" type="number" value="${a.max_rounds || 10}"></div>
    </div>
    <div style="margin-top:12px; display:flex; gap:10px;">
      <label style="display:flex; align-items:center; gap:4px; font-size:12px;"><input type="checkbox" id="agt-reasoning" ${a.enable_reasoning ? 'checked' : ''}> 显式推理</label>
      <label style="display:flex; align-items:center; gap:4px; font-size:12px;"><input type="checkbox" id="agt-memory" ${a.memory_enabled !== false ? 'checked' : ''}> 记忆</label>
      <label style="display:flex; align-items:center; gap:4px; font-size:12px;"><input type="checkbox" id="agt-user-profile" ${a.user_profile_enabled !== false ? 'checked' : ''}> 用户画像</label>
    </div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:10px;">
      <div><label class="agent-info-label">短期记忆轮次</label><input id="agt-mem-turns" class="ncf-input" type="number" min="0" max="100" value="${a.short_term_turns ?? 20}"></div>
      <div><label class="agent-info-label">长期摘要间隔（轮）</label><input id="agt-mem-summary" class="ncf-input" type="number" min="0" max="100" value="${a.long_term_summary_interval ?? 10}"></div>
    </div>
    <div style="margin-top:16px; display:flex; justify-content:flex-end; gap:8px;">
      <button class="btn-test" onclick="showAgentDetail('${a.id || ''}')">取消</button>
      <button class="btn-save" onclick="saveAgent()">💾 保存</button>
    </div>
  `;
}

// 智能体绑定元数据（技能/知识库/MCP/工作流名称映射）
let _agentBindMeta = null;

async function ensureAgentBindMeta() {
  if (_agentBindMeta) return _agentBindMeta;
  const [skills, kbs, mcps, wfs] = await Promise.all([
    api("/api/skills").catch(() => []),
    api("/api/kb/list").catch(() => []),
    api("/api/mcp/servers").catch(() => []),
    api("/api/workflows").catch(() => []),
  ]);
  _agentBindMeta = { skills, kbs, mcps, wfs };
  return _agentBindMeta;
}

function bindName(list, id) {
  const it = (list || []).find(x => x.id === id);
  return it ? (it.name || it.id) : id;
}

function openAgentForm(aid) {
  if (aid) {
    api(`/api/agents/${aid}`).then(a => {
      agentEditing = a;
      ensureAgentBindMeta().then(meta => {
        $("#agent-detail-panel").innerHTML = agentFormTemplate(a, meta);
      });
    });
  } else {
    agentEditing = null;
    ensureAgentBindMeta().then(meta => {
      $("#agent-detail-panel").innerHTML = agentFormTemplate(null, meta);
    });
  }
}

// 复制智能体（内置智能体不可编辑，复制为可编辑副本）
async function openAgentFormCopy(aid) {
  const a = await api(`/api/agents/${aid}`);
  const copy = Object.assign({}, a);
  delete copy.id; delete copy.is_builtin; delete copy.created_at; delete copy.updated_at; delete copy.version; delete copy.enabled;
  copy.name = (a.name || "智能体") + "（副本）";
  agentEditing = copy;
  const meta = await ensureAgentBindMeta();
  $("#agent-detail-panel").innerHTML = agentFormTemplate(copy, meta);
}

async function saveAgent() {
  const id = $("#agt-id").value;
  const body = {
    id,
    name: $("#agt-name").value.trim(),
    icon: $("#agt-icon").value.trim() || "🤖",
    description: $("#agt-desc").value.trim(),
    category: $("#agt-category").value,
    system_prompt: $("#agt-prompt").value,
    builtin_tools: Array.from($$("#agent-detail-panel .agt-tool-cb:checked")).map(cb => cb.value),
    skill_ids: Array.from($$("#agent-detail-panel .agt-skill-cb:checked")).map(cb => cb.value),
    kb_ids: Array.from($$("#agent-detail-panel .agt-kb-cb:checked")).map(cb => cb.value),
    mcp_ids: Array.from($$("#agent-detail-panel .agt-mcp-cb:checked")).map(cb => cb.value),
    workflow_id: ($("#agt-workflow") || {}).value || "",
    kb_top_k: parseInt($("#agt-kb-topk") ? $("#agt-kb-topk").value : 5) || 5,
    kb_score_threshold: parseFloat($("#agt-kb-threshold") ? $("#agt-kb-threshold").value : 0.5) || 0.5,
    show_sources: $("#agt-show-sources") ? $("#agt-show-sources").checked : true,
    short_term_turns: parseInt($("#agt-mem-turns") ? $("#agt-mem-turns").value : 20) || 20,
    long_term_summary_interval: parseInt($("#agt-mem-summary") ? $("#agt-mem-summary").value : 10) || 10,
    user_profile_enabled: $("#agt-user-profile") ? $("#agt-user-profile").checked : true,
    model_preference: $("#agt-model").value.trim(),
    temperature: parseFloat($("#agt-temp").value) || 0.7,
    max_context: parseInt($("#agt-ctx").value) || 128000,
    max_rounds: parseInt($("#agt-rounds").value) || 10,
    enable_reasoning: $("#agt-reasoning").checked,
    memory_enabled: $("#agt-memory").checked,
  };
  if (!body.name) { alert("请填写名称"); return; }
  try {
    if (id) {
      await api(`/api/agents/${id}`, { method: "PUT", body: JSON.stringify(body) });
    } else {
      await api("/api/agents", { method: "POST", body: JSON.stringify(body) });
    }
    alert("保存成功");
    loadAgents("all");
    const saved = id || body.name;
    // 刷新详情
    setTimeout(async () => {
      const list = await api("/api/agents");
      const hit = list.find(x => x.id === id || x.name === body.name);
      if (hit) showAgentDetail(hit.id);
    }, 300);
  } catch (e) {
    alert("保存失败: " + e.message);
  }
}

async function deleteAgent(aid) {
  if (!confirm("确定删除该智能体？")) return;
  try {
    await api(`/api/agents/${aid}`, { method: "DELETE" });
    currentAgentId = null;
    $("#agent-detail-panel").innerHTML = `<div style="text-align:center; color:var(--text-muted); margin-top:80px;"><div style="font-size:48px;">🤖</div><p>已删除</p></div>`;
    loadAgents("all");
  } catch (e) {
    alert("删除失败: " + e.message);
  }
}

let _agentTestAid = null;

async function runAgentTest(aid) {
  const a = await api(`/api/agents/${aid}`);
  _agentTestAid = aid;
  const info = $("#agent-test-model-info");
  const model = a.model_preference || "";
  if (model) {
    const p = (state.providers || []).find(x => (x.models || []).includes(model));
    if (p) {
      const tag = isLocalProvider(p) ? "🏠 本地模型" : "☁️ 公网模型";
      let warn = "";
      if (!isLocalProvider(p) && !p.api_key) {
        if (/free/i.test(model)) {
          warn = `<div style="color:#059669; margin-top:6px;">✅ 免费模型，无需 API Key，可直接测试。</div>`;
        } else {
          warn = `<div style="color:#d97706; margin-top:6px;">⚠️ 该模型需要 API Key（当前供应商未配置），测试将失败（HTTP 401）。请在「设置 → 模型供应商」中为 ${esc(p.name)} 补充 Key。</div>`;
        }
      }
      info.innerHTML = `智能体 <b>${esc(a.name)}</b> · 模型：<b>${esc(model)}</b>（${tag} · ${esc(p.name)}）${warn}`;
    } else {
      info.innerHTML = `智能体 <b>${esc(a.name)}</b> · 模型偏好：<b>${esc(model)}</b>（未匹配到供应商，将回退自动选择）`;
    }
  } else {
    info.innerHTML = `智能体 <b>${esc(a.name)}</b> · 模型：<b>自动选择</b>`;
  }
  const input = $("#agent-test-input");
  input.value = "你好，请介绍一下你自己";
  openModal("agent-test-modal");
  setTimeout(() => input.focus(), 50);
}

function closeAgentTestModal() {
  closeModal("agent-test-modal");
  _agentTestAid = null;
}

async function confirmAgentTest() {
  const aid = _agentTestAid;
  if (!aid) return;
  const text = $("#agent-test-input").value.trim();
  if (!text) { alert("请输入测试任务"); return; }
  closeModal("agent-test-modal");
  _agentTestAid = null;
  const panel = $("#agent-detail-panel");
  panel.innerHTML = `<div style="text-align:center; margin-top:60px; color:var(--text-secondary);"><div style="font-size:36px;">⏳</div><p>智能体运行中...</p></div>`;
  try {
    const r = await api(`/api/agents/${aid}/run`, {
      method: "POST",
      body: JSON.stringify({ message: text, user_id: "ui" })
    });
    if (r.success) {
      panel.innerHTML = `
        <div style="display:flex; align-items:center; gap:10px; margin-bottom:12px;">
          <button class="btn-test" onclick="showAgentDetail('${aid}')">← 返回</button>
          <h3 style="margin:0;">运行结果</h3>
        </div>
        <div style="background:var(--input-bg); border:1px solid var(--border); border-radius:10px; padding:16px; font-size:13px; line-height:1.7;">${renderMarkdown(r.output || '')}</div>`;
      decorateCodeBlocks(panel);
    } else {
      panel.innerHTML = `<div class="bubble error">⚠ ${esc(r.error || '运行失败')}</div><button class="btn-test" style="margin-top:10px;" onclick="showAgentDetail('${aid}')">← 返回</button>`;
    }
  } catch (e) {
    panel.innerHTML = `<div class="bubble error">⚠ ${esc(e.message)}</div><button class="btn-test" style="margin-top:10px;" onclick="showAgentDetail('${aid}')">← 返回</button>`;
  }
}

async function viewAgentMemory(aid) {
  // 简易记忆查看：显示最近短期记忆
  try {
    const r = await api(`/api/agents/${aid}/run`, {
      method: "POST",
      body: JSON.stringify({ message: "（记忆检查）请总结你对我的了解", user_id: "ui" })
    });
    alert(r.success ? "记忆检索完成（见运行结果）" : "记忆不可用");
  } catch (e) {}
}

// 智能体来源页签（内置/创建）
document.addEventListener("click", (e) => {
  const tab = e.target.closest(".agent-source-tab");
  if (!tab) return;
  $$(".agent-source-tab").forEach(t => t.classList.toggle("active", t === tab));
  loadAgents(tab.dataset.source, 1);
  const createBtn = $("#agent-create-btn");
  if (createBtn) createBtn.style.display = tab.dataset.source === 'created' ? '' : 'none';
});

// 记录可用内置工具名（供表单勾选）
(function() {
  window._agentToolNames = ["shell", "file_read", "file_write", "list_files", "web_search", "fetch_url", "search_engine", "get_current_time"];
})();

// ===== 主题切换 =====
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  state.theme = theme;
  localStorage.setItem("abcode-theme", theme);
  const sel = $("#theme-select");
  if (sel) sel.value = theme;
  $$(".theme-pick-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.theme === theme);
  });
  // 粒子/海浪/动效主题：启用相应柔和背景动画（深色星空 / 淡雅白昼 / 海浪波纹）
  if (theme === "particles" || theme === "particles-light") {
    startParticles({ light: theme === "particles-light" });
  } else if (theme === "wave") {
    startWaves();
  } else {
    stopParticles();
    stopWaves();
  }
}

// ===== 海浪背景（仅海浪主题启用，缓慢呼吸、不晃眼） =====
let _wRaf = null;
let _wCtx = null;
let _wT = 0;

function startWaves() {
  stopWaves(); // 幂等：先清旧
  let canvas = $("#wave-bg");
  if (!canvas) {
    canvas = document.createElement("canvas");
    canvas.id = "wave-bg";
    document.body.appendChild(canvas);
  }
  canvas.style.display = "block";
  const ctx = canvas.getContext("2d");
  _wCtx = ctx;

  const resize = () => {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  };
  resize();
  window.addEventListener("resize", resize);

  // 三层波浪：低透明度浅蓝，缓慢左右漂移（上浮节奏）
  const layers = [
    { amp: 26, speed: 0.012, phase: 0, alpha: 0.16, base: canvas.height * 0.82, color: "90,180,215" },
    { amp: 20, speed: 0.018, phase: 1.7, alpha: 0.14, base: canvas.height * 0.88, color: "120,200,225" },
    { amp: 34, speed: 0.010, phase: 3.2, alpha: 0.18, base: canvas.height * 0.93, color: "70,150,195" },
  ];

  const draw = (t) => {
    const s = t / 1000;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const L of layers) {
      ctx.beginPath();
      ctx.moveTo(0, L.base);
      for (let x = 0; x <= canvas.width; x += 8) {
        const y = L.base + Math.sin(x * 0.010 + s * L.speed + L.phase) * L.amp;
        ctx.lineTo(x, y);
      }
      ctx.lineTo(canvas.width, canvas.height);
      ctx.lineTo(0, canvas.height);
      ctx.closePath();
      ctx.fillStyle = L.color;
      ctx.globalAlpha = L.alpha;
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    if (state.particleAnimate) _wRaf = requestAnimationFrame(draw);
    else { _wRaf = null; } // 动画关：停顿在当前画面
  };
  _wRaf = requestAnimationFrame(draw);
}

function stopWaves() {
  if (_wRaf) { cancelAnimationFrame(_wRaf); _wRaf = null; }
  const canvas = $("#wave-bg");
  if (canvas) canvas.style.display = "none";
  _wCtx = null;
  _wT = 0;
}
let _pCtx = null;
let _pParticles = [];
let _pRaf = null;

function startParticles(opts = {}) {
  const light = !!opts.light;
  stopParticles(); // 幂等：先清旧
  let canvas = $("#particle-bg");
  if (!canvas) {
    canvas = document.createElement("canvas");
    canvas.id = "particle-bg";
    document.body.appendChild(canvas);
  }
  canvas.style.display = "block";
  const ctx = canvas.getContext("2d");
  _pCtx = ctx;

  const resize = () => {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  };
  resize();
  window.addEventListener("resize", resize);

  // 生成粒子：数量适中，柔和不刺眼；深色/白昼两种色板
  const count = Math.min(120, Math.floor(window.innerWidth / 14));
  _pParticles = Array.from({ length: count }, () => {
    // 白昼：偏淡蓝/紫的低饱和浅色，透明度更淡；夜空：蓝紫星光
    const hue = light ? 200 + Math.random() * 60 : 205 + Math.random() * 50;
    const sat = light ? 40 : 60;
    const lum = light ? 78 : 70;
    const a = light ? 0.05 + Math.random() * 0.20 : 0.06 + Math.random() * 0.28;
    return {
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      r: 0.6 + Math.random() * 1.8,           // 小半径，避免刺眼
      vx: (Math.random() - 0.5) * 0.18,        // 慢速漂移
      vy: -0.05 - Math.random() * 0.18,        // 缓慢上浮
      a,
      hue, sat, lum,
    };
  });

  let last = performance.now();
  // 统一渲染一帧（不移动粒子）
  const renderFrame = () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const p of _pParticles) {
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = `hsla(${p.hue}, ${p.sat}%, ${p.lum}%, ${p.a})`;
      ctx.fill();
    }
  };
  const draw = (t) => {
    const dt = Math.min(0.05, (t - last) / 1000);
    last = t;
    for (const p of _pParticles) {
      p.x += p.vx * dt * 60;
      p.y += p.vy * dt * 60;
      if (p.y < -10) { p.y = canvas.height + 10; p.x = Math.random() * canvas.width; }
      if (p.x < -10) p.x = canvas.width + 10;
      if (p.x > canvas.width + 10) p.x = -10;
    }
    renderFrame();
    _pRaf = requestAnimationFrame(draw);
  };
  if (state.particleAnimate) {
    _pRaf = requestAnimationFrame(draw);
  } else {
    renderFrame(); // 动画关闭：只画一帧静态
  }
}

function stopParticles() {
  if (_pRaf) { cancelAnimationFrame(_pRaf); _pRaf = null; }
  const canvas = $("#particle-bg");
  if (canvas) canvas.style.display = "none";
  _pCtx = null;
  _pParticles = [];
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
  // 切会话/加载后默认位于底部，并重置未读计数
  _atBottom = true;
  _pendingNew = 0;
  scrollBottom();
  syncReadMoreBar();
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
function isLocalProvider(p) {
  if (!p || !p.base_url) return false;
  const b = String(p.base_url).toLowerCase();
  return b.includes("localhost") || b.includes("127.0.0.1") || b.includes("11434") || p.type === "ollama";
}

function getProvider(id) {
  return state.providers.find((p) => p.id === id);
}

function updateProviderSelect() {
  const sel = $("#provider-select");
  sel.innerHTML = "";
  // 根据类型过滤供应商
  const filtered = state.providers.filter(p => {
    if (state.modelTypeFilter === "all") return true;
    const isLocal = p.base_url.includes("localhost") || p.base_url.includes("127.0.0.1") || p.base_url.includes("11434");
    return state.modelTypeFilter === "local" ? isLocal : !isLocal;
  });
  filtered.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.name;
    sel.appendChild(opt);
  });
  // 如果当前选中的供应商不在过滤结果中，切换到第一个
  if (filtered.length > 0 && !filtered.find(p => p.id === state.currentProviderId)) {
    state.currentProviderId = filtered[0].id;
  }
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
  let picked = null;
  if (models.includes(state.currentModel)) picked = state.currentModel;
  else if (p.default_model && models.includes(p.default_model)) picked = p.default_model;
  if (!picked) picked = models.find(m => /free/i.test(m)) || models[0];
  sel.value = picked;
  state.currentModel = picked;
  syncInputModelSelect();
}

// 同步输入区模型快捷选择
function syncInputModelSelect() {
  const sel = $("#input-model-select");
  if (!sel) return;
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
  let picked = null;
  if (models.includes(state.currentModel)) picked = state.currentModel;
  else if (p.default_model && models.includes(p.default_model)) picked = p.default_model;
  if (!picked) picked = models.find(m => /free/i.test(m)) || models[0];
  sel.value = picked;
  state.currentModel = picked;
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
  if (p && p.models.length && !state.currentModel) state.currentModel = p.models.find(x => /free/i.test(x)) || p.models[0];
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
    btn.textContent = "🔍 获取全部";
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

// ===== 获取免费模型列表 =====
async function fetchFreeModels() {
  const url = $("#pf-url").value.trim();
  const key = $("#pf-key").value.trim();
  if (!url) { alert("请先填写 Base URL"); return; }
  const btn = $("#fetch-free-models-btn");
  btn.disabled = true;
  btn.textContent = "⏳ 获取中...";
  try {
    const r = await api("/api/providers/models", {
      method: "POST",
      body: JSON.stringify({ base_url: url, api_key: key }),
    });
    if (r.ok && r.free_models && r.free_models.length) {
      $("#pf-models").value = r.free_models.join(", ");
      renderModelTags(r.free_models, r.free_models);
      // 自动填入上下文长度
      if (r.max_context && !$("#pf-context").value) {
        $("#pf-context").value = r.max_context;
      }
      alert(`✨ 已获取 ${r.free_models.length} 个免费模型`);
    } else if (r.ok && r.models.length) {
      // 没有明确的免费模型列表，用关键词过滤
      const freeKeywords = ["free", "flash", "mini", "lite", "tiny", "small"];
      const freeModels = r.models.filter(m => freeKeywords.some(k => m.toLowerCase().includes(k)));
      if (freeModels.length) {
        $("#pf-models").value = freeModels.join(", ");
        renderModelTags(freeModels, freeModels);
        alert(`✨ 已获取 ${freeModels.length} 个免费模型（关键词匹配）`);
      } else {
        alert("未找到免费模型，请手动选择");
      }
    } else {
      alert(r.msg || "未获取到模型列表");
    }
  } catch (e) {
    alert("获取失败: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "✨ 获取免费";
  }
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
    const engine = settings.search_engine || "builtin";
    $("#search-engine").value = engine;
    $("#search-url").value = settings.search_service_url || "";
    $("#search-key").value = settings.search_api_key || "";
    // 内置搜索时隐藏 URL 字段
    toggleSearchUrlGroup(engine);
  } catch (e) {}
}

function toggleSearchUrlGroup(engine) {
  const group = document.getElementById("search-url-group");
  if (group) {
    group.style.display = (engine === "builtin") ? "none" : "block";
  }
}

// 监听引擎切换
document.addEventListener("DOMContentLoaded", () => {
  const sel = document.getElementById("search-engine");
  if (sel) {
    sel.addEventListener("change", () => toggleSearchUrlGroup(sel.value));
  }
});

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
  const engine = $("#search-engine").value;
  const box = $("#search-test-result");
  box.textContent = "测试中...";
  box.className = "test-result ok";
  box.style.display = "block";

  if (engine === "builtin") {
    // 内置搜索直接测试
    try {
      const r = await api("/api/search", { method: "POST", body: JSON.stringify({ query: "hello world", engine: "bing", max_results: 3 }) });
      if (r.ok && r.results && r.results.length > 0) {
        box.textContent = `✅ 内置搜索正常！返回 ${r.results.length} 条结果`;
        box.className = "test-result ok";
      } else {
        box.textContent = "⚠️ 内置搜索返回为空，可能网络受限";
        box.className = "test-result fail";
      }
    } catch (e) {
      box.textContent = "❌ 测试失败: " + e.message;
      box.className = "test-result fail";
    }
    return;
  }

  const body = {
    search_engine: engine,
    search_service_url: $("#search-url").value.trim(),
  };
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
let currentKbId = "default";

async function loadChatKbSelect() {
  const sel = $("#chat-kb-select");
  if (!sel) return;
  try {
    const kbs = await api("/api/kb/list");
    let html = `<option value="">🌐 全部知识库</option>`;
    html += kbs.map(k => `<option value="${escAttr(k.id)}">${esc(k.name)}</option>`).join("");
    sel.innerHTML = html;
    sel.value = state.chatKbId || "";
  } catch (e) {
    sel.innerHTML = `<option value="">🌐 全部知识库</option>`;
  }
}

function onChatKbChange(kbId) {
  state.chatKbId = kbId || "";
  localStorage.setItem("abcode-chat-kb", state.chatKbId);
}

function openKb() {
  $("#kb-modal").style.display = "flex";
  loadKbList();
  loadKbDocs();
  loadChatKbSelect();
  setupKbDropzone();
}

function closeKb() {
  $("#kb-modal").style.display = "none";
}

function openKbDetail(id) {
  $("#kb-detail-modal").style.display = "flex";
  $("#kb-detail-title").textContent = "📄 加载中...";
  $("#kb-detail-body").innerHTML = '<p class="hint">加载中...</p>';
  api(`/api/kb/docs/${id}`).then((d) => {
    $("#kb-detail-title").textContent = `📄 ${d.name}`;
    const t = fmtTime(d.created_at);
    let html = `<div class="kb-detail-meta">
      <span class="kb-type-tag">${esc(d.type)}</span>
      <span>${d.chunks} 分块</span>
      <span>${(d.size / 1024).toFixed(1)} KB</span>
      <span>${t}</span>
    </div>`;
    html += `<div class="kb-detail-chunks">`;
    d.chunk_list.forEach((c) => {
      html += `<div class="kb-detail-chunk">
        <div class="kdc-head">分块 #${c.idx + 1}</div>
        <pre class="kdc-content">${esc(c.content)}</pre>
      </div>`;
    });
    html += `</div>`;
    $("#kb-detail-body").innerHTML = html;
  }).catch((e) => {
    $("#kb-detail-body").innerHTML = `<p class="hint">加载失败: ${e.message}</p>`;
  });
}

function closeKbDetail() {
  $("#kb-detail-modal").style.display = "none";
}

async function loadKbList() {
  try {
    const kbs = await api("/api/kb/list");
    const sel = $("#kb-select");
    if (!sel) return;
    sel.innerHTML = kbs.map(k => `<option value="${escAttr(k.id)}">${esc(k.name)} (${k.doc_count})</option>`).join("");
    if (!kbs.some(k => k.id === currentKbId)) currentKbId = "default";
    sel.value = currentKbId;
  } catch (e) { /* 面板未打开时忽略 */ }
}

function switchKb(kbId) {
  currentKbId = kbId || "default";
  loadKbDocs();
}

async function createKbPrompt() {
  const name = prompt("新建知识库名称:");
  if (!name || !name.trim()) return;
  try {
    const res = await api("/api/kb/create", {
      method: "POST",
      body: JSON.stringify({ name: name.trim() }),
    });
    currentKbId = res.id;
    await loadKbList();
    loadKbDocs();
  } catch (e) { alert(`创建失败: ${e.message}`); }
}

async function deleteKbPrompt() {
  if (currentKbId === "default") { alert("默认知识库不可删除"); return; }
  const kbs = await api("/api/kb/list").catch(() => []);
  const kb = kbs.find(k => k.id === currentKbId);
  if (!confirm(`确定删除知识库「${kb ? kb.name : currentKbId}」？其下所有文档将一并删除！`)) return;
  try {
    await api(`/api/kb/${currentKbId}`, { method: "DELETE" });
    currentKbId = "default";
    await loadKbList();
    loadKbDocs();
  } catch (e) { alert(`删除失败: ${e.message}`); }
}

async function loadKbDocs() {
  const [docs, stats] = await Promise.all([
    api(`/api/kb/docs${currentKbId ? `?kb_id=${encodeURIComponent(currentKbId)}` : ""}`),
    api(`/api/kb/stats${currentKbId ? `?kb_id=${encodeURIComponent(currentKbId)}` : ""}`).catch(() => null),
  ]);
  window._kbAllDocs = docs || [];
  if (stats) {
    $("#kb-stats").style.display = "flex";
    $("#kb-stat-docs").textContent = stats.doc_count;
    $("#kb-stat-chunks").textContent = stats.chunk_count;
    $("#kb-stat-size").textContent = (stats.total_size / 1024).toFixed(1) + " KB";
  }
  const filterInput = $("#kb-doc-filter-input");
  if (filterInput) filterInput.value = "";
  renderKbDocs(window._kbAllDocs);
}

function filterKbDocs() {
  const kw = ($("#kb-doc-filter-input").value || "").trim().toLowerCase();
  const docs = (window._kbAllDocs || []).filter(
    (d) => !kw || d.name.toLowerCase().includes(kw)
  );
  renderKbDocs(docs);
}

function renderKbDocs(docs) {
  const list = $("#kb-doc-list");
  list.innerHTML = "";
  if (!docs.length) {
    list.innerHTML = (window._kbAllDocs && window._kbAllDocs.length)
      ? '<p class="hint">没有匹配的文档。</p>'
      : '<p class="hint">知识库为空，上传文档后开始构建。</p>';
    return;
  }
  docs.forEach((d) => {
    const el = document.createElement("div");
    el.className = "kb-doc";
    const t = fmtTime(d.created_at);
    const icon = d.ext === "md" || d.ext === "markdown" ? "📝"
      : d.ext === "pdf" ? "📕"
      : d.ext === "doc" || d.ext === "docx" ? "📘"
      : d.ext === "csv" || d.ext === "tsv" ? "📊"
      : d.ext === "json" ? "🧾" : "📄";
    el.innerHTML = `
      <div class="kd-main">
        <div class="kd-name">${icon} ${esc(d.name)} <span class="kb-type-tag">${esc(d.type)}</span></div>
        <div class="kd-meta">${d.chunks} 分块 · ${(d.size / 1024).toFixed(1)}KB · ${t}</div>
      </div>
      <div class="kd-actions">
        <button class="kd-btn" title="查看详情" onclick="openKbDetail('${d.id}')">👁</button>
        <button class="kd-btn" title="重命名" onclick="renameKbDoc('${d.id}', '${escAttr(d.name)}')">✏️</button>
        <button class="kd-btn kd-del" title="删除" onclick="deleteKbDoc('${d.id}')">🗑</button>
      </div>`;
    list.appendChild(el);
  });
}

async function renameKbDoc(id, oldName) {
  const name = prompt("重命名文档:", oldName);
  if (!name || name.trim() === oldName) return;
  try {
    await api(`/api/kb/docs/${id}/rename`, {
      method: "POST",
      body: JSON.stringify({ name: name.trim() }),
    });
    loadKbDocs();
  } catch (e) {
    alert(`重命名失败: ${e.message}`);
  }
}

async function uploadKb() {
  const input = $("#kb-file");
  if (!input.files.length) { alert("请选择文件"); return; }
  const files = [...input.files];
  let ok = 0, fail = 0, dups = 0, fails = [];
  for (const f of files) {
    const fd = new FormData();
    fd.append("file", f);
    fd.append("kb_id", currentKbId || "default");
    try {
      const resp = await fetch("/api/kb/upload", { method: "POST", body: fd });
      if (resp.ok) {
        const data = await resp.json().catch(() => ({}));
        if (data.duplicate) dups++;
        else ok++;
      }
      else {
        fail++;
        const err = await resp.json().catch(() => ({}));
        fails.push(`${f.name}: ${err.detail || resp.status}`);
      }
    } catch (e) { fail++; fails.push(`${f.name}: ${e.message}`); }
  }
  const parts = [];
  if (ok) parts.push(`成功 ${ok} 个`);
  if (dups) parts.push(`重复跳过 ${dups} 个`);
  if (fail) parts.push(`失败 ${fail} 个`);
  alert(`上传完成：${parts.join("，") || "无变化"}${fails.length ? `\n${fails.join("\n")}` : ""}`);
  input.value = "";
  loadKbDocs();
  loadKbList();
}

function exportKb() {
  const q = currentKbId ? `?kb_id=${encodeURIComponent(currentKbId)}` : "";
  window.location.href = `/api/kb/export${q}`;
}

async function clearKb() {
  if (!confirm("确定清空当前知识库？此操作不可恢复！")) return;
  if (!confirm("再次确认：将删除当前知识库的所有文档和索引。")) return;
  await api("/api/kb/clear", {
    method: "POST",
    body: JSON.stringify({ kb_id: currentKbId || null }),
  });
  loadKbDocs();
  loadKbList();
}

function setupKbDropzone() {
  const dz = $("#kb-dropzone");
  const fileInput = $("#kb-file");
  if (!dz || !fileInput) return;
  ["dragenter", "dragover"].forEach((ev) => {
    dz.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dz.classList.add("kb-dragover");
    });
  });
  ["dragleave", "drop"].forEach((ev) => {
    dz.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dz.classList.remove("kb-dragover");
    });
  });
  dz.addEventListener("drop", (e) => {
    const files = e.dataTransfer.files;
    if (!files || !files.length) return;
    fileInput.files = files;
    uploadKb();
  });
}

async function kbTestSearch() {
  const q = $("#kb-test-input").value.trim();
  const box = $("#kb-test-results");
  if (!q) { box.style.display = "none"; return; }
  box.style.display = "block";
  box.innerHTML = '<p class="hint">搜索中...</p>';
  try {
    const results = await api("/api/kb/search", {
      method: "POST",
      body: JSON.stringify({ query: q, top_k: 5, highlight: true, kb_id: currentKbId || null }),
    });
    if (!results.length) {
      box.innerHTML = '<p class="hint">未找到相关内容，试试更具体的关键词</p>';
      return;
    }
    let html = `<div class="kb-test-head">找到 ${results.length} 条相关片段（混合打分排序）</div>`;
    results.forEach((r) => {
      const shown = (r.highlight || r.snippet || r.content).slice(0, 300);
      const bd = r.breakdown || {};
      const scoreBar = Math.min(100, Math.round((r.score || 0) * 100));
      const detail = [
        `BM25 ${Math.round((bd.bm25_norm ?? 0) * 100)}%`,
        `短语 ${Math.round((bd.phrase ?? 0) * 100)}%`,
        `覆盖 ${Math.round((bd.coverage ?? 0) * 100)}%`,
        `位置 ${Math.round((bd.position ?? 0) * 100)}%`,
      ].join(" · ");
      html += `<div class="kb-test-item">
        <div class="kti-doc">📄 ${esc(r.doc_name)} <span class="kb-type-tag">${esc(r.doc_type || "文档")}</span> <span class="kti-score">综合 ${r.score}</span></div>
        <div class="kti-bar"><div class="kti-bar-fill" style="width:${scoreBar}%"></div></div>
        <div class="kti-breakdown">${detail}</div>
        <div class="kti-content">${shown}</div>
      </div>`;
    });
    box.innerHTML = html;
  } catch (e) {
    box.innerHTML = `<p class="hint">搜索失败: ${e.message}</p>`;
  }
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
    const last = j.last_run ? fmtTime(j.last_run) : "从未";
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

// ===== 流式阅读跟随：仅当用户在底部时自动滚动；否则显示「下拉阅读」悬浮条 =====
let _atBottom = true;       // 用户当前是否停留在最新底部附近
let _pendingNew = 0;         // 生成中新增的未读条数（供悬浮条计数）

function isNearBottom(area) {
  if (!area) area = $("#chat-area");
  if (!area) return true;
  return area.scrollHeight - area.scrollTop - area.clientHeight < 60;
}

// 更新当前底部跟随状态，并在用户滚离底部且正生成时显示「下拉阅读」提示
function onChatScroll() {
  const area = $("#chat-area");
  const was = _atBottom;
  _atBottom = isNearBottom(area);
  if (!_atBottom && was) {
    // 刚从底部滚上去：重置未读计数（视为重新开始阅读上方内容）
    _pendingNew = 0;
  }
  syncReadMoreBar();
}

function syncReadMoreBar() {
  const bar = $("#read-more-bar");
  const text = $("#rmb-text");
  if (!bar) return;
  const area = $("#chat-area");
  const streaming = state.streaming;
  // 用户滚离底部且下方仍有内容时展示；生成中显示「运行中」状态点
  const shouldShow = !_atBottom && hasContent(area);
  if (shouldShow) {
    bar.style.display = "flex";
    bar.classList.toggle("running", streaming);
    const label = streaming ? "运行中" : "回到最新";
    const count = _pendingNew > 0 ? ` · ${_pendingNew} 条新内容` : "";
    text.textContent = `${streaming ? "🔴" : "⬇"} ${label}${count} · ${streaming ? "阅读到当前" : "跳到底部"}`;
  } else {
    bar.style.display = "none";
  }
}

function hasContent(area) {
  const msgs = $("#messages");
  return !!(msgs && msgs.children.length);
}

// 点击「阅读到当前」：跳到最新生成位置并恢复跟随状态
function jumpToLatest() {
  scrollBottom();
  _atBottom = true;
  _pendingNew = 0;
  syncReadMoreBar();
}

// 智能跟随：用户在底部才自动滚动；否则保留当前位置并同步悬浮条
function follow() {
  _atBottom = isNearBottom();
  if (_atBottom) {
    scrollBottom();
  }
  syncReadMoreBar();
}

// 始终跳到底部（用户主动点按/非流式场景）
function followLatest() {
  scrollBottom();
  _atBottom = true;
  syncReadMoreBar();
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
      body: JSON.stringify({ query, top_k: 5, highlight: true }),
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
      // 后端 highlight 字段已含 <mark> 高亮，优先用 snippet 中心的片段
      const shown = (r.highlight || r.snippet || r.content).slice(0, 400);
      el.innerHTML = `
        <div class="krr-doc">📄 ${esc(r.doc_name)} <span class="kb-type-tag">${esc(r.doc_type || "文档")}</span> <span class="krr-score">${r.score}</span></div>
        <div class="krr-content">${shown}</div>`;
      el.onclick = () => insertKbRef(r);
      box.appendChild(el);
    });
  } catch (e) {
    $("#kb-ref-results").innerHTML = `<div class="kb-ref-empty">搜索失败: ${e.message}</div>`;
  }
}

function insertKbRef(result) {
  const input = $("#chat-input");
  const content = (result.snippet || result.content || "").trim();
  const ref = `\n[引用知识库「${result.doc_name}」]\n${content}\n[/引用]\n`;
  const pos = input.selectionStart;
  input.value = input.value.slice(0, pos) + ref + input.value.slice(pos);
  input.focus();
  autoResize();
  closeKbRef();
}

// ===== 语音输入（Web Speech API） =====
let recognition = null;
let recording = false;
let voiceBase = ""; // 本次语音开始前输入框已有文本
let voiceSupported = !!(window.SpeechRecognition || window.webkitSpeechRecognition);

function initSpeech() {
  if (!voiceSupported) {
    const btn = $("#voice-btn");
    if (btn) btn.style.display = "none";
    return;
  }
  const btn = $("#voice-btn");
  if (!btn) return;
  // 按住说话：pointerdown 开始，pointerup / 移出停止
  btn.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    startVoice();
  });
  btn.addEventListener("pointerup", stopVoice);
  btn.addEventListener("pointerleave", stopVoice);
}

// 每次新建实例，避免 stop/error 后实例失效（InvalidStateError）
function getRecognition() {
  if (recognition) return recognition;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return null;
  const r = new SR();
  r.lang = "zh-CN";
  r.interimResults = true;
  r.continuous = false;
  r.maxAlternatives = 1;
  r.onresult = (e) => {
    const input = $("#chat-input");
    if (!input) return;
    const result = e.results[0];
    if (!result) return;
    const text = result[0].transcript;
    if (result.isFinal) {
      input.value = voiceBase + text;
      autoResize();
      stopVoice();
    } else {
      // 实时预览中间结果
      input.value = voiceBase + text;
      autoResize();
    }
  };
  r.onerror = (e) => {
    let msg = "语音识别出错";
    if (e.error === "not-allowed" || e.error === "service-not-allowed") msg = "无法访问麦克风，请在浏览器设置中允许";
    else if (e.error === "no-speech") msg = "未检测到语音，请重试";
    else if (e.error === "network") msg = "语音识别网络错误";
    else if (e.error === "aborted") return; // 用户主动停止，静默
    recording = false;
    const btn = $("#voice-btn");
    if (btn) btn.classList.remove("recording");
    if (msg) alert(msg);
  };
  r.onend = () => {
    recording = false;
    const btn = $("#voice-btn");
    if (btn) btn.classList.remove("recording");
    recognition = null; // 释放实例，下次重建
  };
  recognition = r;
  return r;
}

function startVoice() {
  const r = getRecognition();
  if (!r) { alert("当前浏览器不支持语音输入，请使用 Chrome / Edge"); return; }
  if (recording) { stopVoice(); return; }
  recording = true;
  voiceBase = $("#chat-input").value;
  const btn = $("#voice-btn");
  if (btn) btn.classList.add("recording");
  try {
    r.start();
  } catch (e) {
    // 实例状态异常：重建后重试一次
    recognition = null;
    recording = false;
    if (btn) btn.classList.remove("recording");
    const r2 = getRecognition();
    if (r2) {
      try {
        recording = true;
        voiceBase = $("#chat-input").value;
        if (btn) btn.classList.add("recording");
        r2.start();
      } catch (e2) {
        recording = false;
        if (btn) btn.classList.remove("recording");
        alert("语音输入启动失败，请重试");
      }
    }
  }
}

function stopVoice() {
  if (!recording) return;
  recording = false;
  const btn = $("#voice-btn");
  if (btn) btn.classList.remove("recording");
  try { if (recognition) recognition.stop(); } catch (e) {}
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
          <button class="ch-btn" onclick="openChannelConfig('${ch.id}')">⚙ 配置</button>
          <button class="ch-btn" onclick="openChannelQr('${ch.id}')">📱 扫码</button>
          <button class="ch-btn" onclick="openChannelMsgs('${ch.id}')">💬 消息</button>
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
        <button class="ch-grid-btn" onclick="openChannelConfig('${ch.id}')">⚙ 配置</button>
        <button class="ch-grid-btn" onclick="openChannelQr('${ch.id}')">📱 扫码</button>
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

// ===== 频道配置参数 =====
// 各渠道可配置参数（key -> 中文标签）
const CHANNEL_FIELDS = {
  wechat: [["app_id", "AppID"], ["app_secret", "AppSecret"], ["token", "Token"], ["aes_key", "AES Key"]],
  wecom: [["corp_id", "企业ID"], ["agent_id", "应用 AgentId"], ["secret", "Secret"], ["token", "Token"], ["encoding_aes_key", "EncodingAESKey"]],
  dingtalk: [["app_key", "AppKey"], ["app_secret", "AppSecret"], ["webhook_token", "Webhook Token"], ["sign_secret", "加签密钥"]],
  feishu: [["app_id", "App ID"], ["app_secret", "App Secret"], ["verify_token", "Verification Token"], ["encrypt_key", "Encrypt Key"]],
  telegram: [["bot_token", "Bot Token"]],
  discord: [["bot_token", "Bot Token"]],
  qq: [["bot_appid", "Bot AppID"], ["bot_token", "Bot Token"], ["bot_secret", "Bot Secret"]],
  slack: [["bot_token", "Bot Token"], ["signing_secret", "Signing Secret"]],
  matrix: [["homeserver", "Homeserver 地址"], ["access_token", "Access Token"]],
  mqtt: [["broker_url", "Broker 地址"], ["username", "用户名"], ["password", "密码"], ["topic", "订阅主题"]],
  onebot: [["ws_url", "WebSocket 地址"], ["access_token", "Access Token"]],
  sip: [["server", "SIP 服务器"], ["username", "账号"], ["password", "密码"]],
  voice: [["provider", "语音服务商"], ["app_key", "AppKey"], ["app_secret", "AppSecret"]],
  default: [["webhook_url", "Webhook URL"], ["api_key", "API Key"], ["secret", "Secret"]]
};

let currentChannelConfig = null;

async function openChannelConfig(cid) {
  const channels = await api("/api/channels");
  const ch = channels.find((c) => c.id === cid);
  if (!ch) return;
  currentChannelConfig = ch;
  $("#chcfg-title").textContent = `⚙ ${ch.name} 配置`;
  const fields = CHANNEL_FIELDS[ch.type] || CHANNEL_FIELDS.default;
  const cfg = ch.config || {};
  const rows = fields.map(([key, label]) => {
    const val = (cfg[key] ?? "").toString().split('"').join("&quot;");
    return `<div class="chcfg-row">
      <label>${label}</label>
      <input id="chcfg-${key}" type="text" value="${val}" placeholder="请输入 ${label}" autocomplete="off">
    </div>`;
  }).join("");
  const prefix = (ch.bot_prefix || "").split('"').join("&quot;");
  const desc = (ch.description || "").split('"').join("&quot;");
  $("#chcfg-fields").innerHTML = rows + `
    <div class="chcfg-row"><label>机器人前缀</label><input id="chcfg-bot_prefix" type="text" value="${prefix}" placeholder="如：@bot 或 /" autocomplete="off"></div>
    <div class="chcfg-row"><label>描述</label><input id="chcfg-description" type="text" value="${desc}" autocomplete="off"></div>`;
  $("#channel-config-modal").style.display = "flex";
}

function closeChannelConfig() {
  $("#channel-config-modal").style.display = "none";
  currentChannelConfig = null;
}

async function saveChannelConfig() {
  if (!currentChannelConfig) return;
  const ch = currentChannelConfig;
  const fields = CHANNEL_FIELDS[ch.type] || CHANNEL_FIELDS.default;
  const cfg = {};
  fields.forEach(([key]) => {
    const v = $(`#chcfg-${key}`)?.value?.trim() ?? "";
    if (v) cfg[key] = v;
  });
  const body = { config: cfg };
  const bp = $("#chcfg-bot_prefix")?.value?.trim() ?? "";
  if (bp !== (ch.bot_prefix || "")) body.bot_prefix = bp;
  await api(`/api/channels/${ch.id}/config`, { method: "POST", body });
  closeChannelConfig();
  loadChannels();
  alert(`✅ 「${ch.name}」配置已保存`);
}

// ===== 频道扫码接入 =====
const CHANNEL_HINT_FOR = {
  wechat: "微信无官方个人 Bot 接口；若走通用通道，请以外部分发器把微信消息转换为 POST JSON {sender,text} 调用消息面板中的 Webhook 地址。",
  dingtalk: "钉钉：扫码启用后，还需在「配置」中填写 AppKey/AppSecret，ABcode 即通过 Stream 长连接接收钉钉消息（免公网）。",
  wecom: "企业微信：需在配置填写 corp_id / agent_id / secret，并外网回调接转到消息面板的 Webhook 地址。",
  feishu: "飞书：需在配置填写 app_id / app_secret，并外网回调接转到消息面板的 Webhook 地址。",
  default: "通用通道：确认接入后即可通过「消息」面板中的 Webhook 接口收发对话（POST JSON {sender, text}）。"
};

let currentMsgsChannelId = null;

async function openChannelMsgs(cid) {
  const channels = await api("/api/channels");
  const ch = channels.find((c) => c.id === cid);
  if (!ch) return;
  currentMsgsChannelId = cid;
  $("#chmsgs-title").textContent = `💬 ${ch.name} 消息`;
  $("#chmsgs-webhook").textContent = `POST http://${location.host}/api/channels/${cid}/webhook`;
  $("#channel-msgs-modal").style.display = "flex";
  await loadChannelMsgs(cid);
}

async function loadChannelMsgs(cid) {
  const list = await api(`/api/channels/${cid}/messages?limit=100`);
  const box = $("#chmsgs-list");
  if (!list || !list.length) {
    box.innerHTML = '<p class="hint" style="text-align:center;padding:20px;">暂无消息。用下方输入框模拟一条频道对话，或向 Webhook 地址 POST 消息。</p>';
    return;
  }
  box.innerHTML = list.map((m) => {
    const t = new Date(m.created_at * 1000);
    const time = `${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`;
    const who = m.role === "assistant" ? "🤖 ABcode" : `👤 ${esc(m.sender || "用户")}`;
    const cls = m.role === "assistant" ? "chmsg-a" : "chmsg-u";
    return `<div class="chmsg ${cls}"><div class="chmsg-meta">${who} <span style="color:var(--muted);font-size:11px;">${time}</span></div><div class="chmsg-body">${esc(m.content).replace(/\n/g, "<br>")}</div></div>`;
  }).join("");
}

function closeChannelMsgs() {
  $("#channel-msgs-modal").style.display = "none";
  currentMsgsChannelId = null;
}

async function sendChannelTestMsg() {
  if (!currentMsgsChannelId) return;
  const text = $("#chmsgs-test-text").value.trim();
  if (!text) { alert("请输入消息内容"); return; }
  const sender = $("#chmsgs-test-sender").value.trim() || "测试用户";
  await api(`/api/channels/${currentMsgsChannelId}/send`, {
    method: "POST",
    body: { sender, text }
  });
  $("#chmsgs-test-text").value = "";
  await loadChannelMsgs(currentMsgsChannelId);
}

async function clearChannelMsgs() {
  if (!currentMsgsChannelId) return;
  if (!confirm("确认清空该频道的消息记录？")) return;
  await api(`/api/channels/${currentMsgsChannelId}/messages`, { method: "DELETE" });
  await loadChannelMsgs(currentMsgsChannelId);
}

let currentQrChannelId = null;
let currentQrPollTimer = null;
let currentQrGenerating = false;

async function openChannelQr(cid) {
  if (currentQrGenerating) return;  // 生成中禁止连点
  currentQrGenerating = true;
  const channels = await api("/api/channels");
  const ch = channels.find((c) => c.id === cid);
  if (!ch) { currentQrGenerating = false; return; }
  currentQrChannelId = cid;
  $("#chqr-title").textContent = `📱 ${ch.name} 扫码接入`;
  $("#chqr-tip").textContent = "请用手机扫码，在手机上确认接入该频道";
  $("#chqr-status").textContent = "";
  const hint = CHANNEL_HINT_FOR[ch.type] || CHANNEL_HINT_FOR.default;
  $("#chqr-webhook-hint").textContent = hint.replace("{cid}", cid).replace("{host}", location.host);
  $("#chqr-qr").innerHTML = '<span class="hint" style="color:var(--muted)">生成中…</span>';
  const refreshBtn = document.querySelector("#channel-qr-modal .ch-btn[onclick*='openChannelQr']");
  if (refreshBtn) refreshBtn.disabled = true;
  $("#channel-qr-modal").style.display = "flex";

  const r = await api(`/api/channels/${cid}/qr`, { method: "POST" });
  if (!r.ok) {
    $("#chqr-qr").innerHTML = `<span class="hint" style="color:#dc2626">${esc(r.detail || "生成失败")}</span>`;
    currentQrGenerating = false;
    if (refreshBtn) refreshBtn.disabled = false;
    return;
  }
  const img = new Image();
  img.src = `/api/channels/${cid}/qr/png?code=${encodeURIComponent(r.code)}`;
  img.width = 240;
  img.height = 240;
  img.style.borderRadius = "8px";
  img.onload = () => { $("#chqr-qr").innerHTML = ""; $("#chqr-qr").appendChild(img); currentQrGenerating = false; if (refreshBtn) refreshBtn.disabled = false; };
  img.onerror = () => { $("#chqr-qr").innerHTML = '<span class="hint" style="color:#dc2626">二维码生成失败</span>'; currentQrGenerating = false; if (refreshBtn) refreshBtn.disabled = false; };

  if (currentQrPollTimer) clearInterval(currentQrPollTimer);
  currentQrPollTimer = setInterval(async () => {
    const s = await api(`/api/channels/${cid}/qr/status`);
    if (!s) return;
    if (s.status === "confirmed") {
      clearInterval(currentQrPollTimer);
      currentQrPollTimer = null;
      $("#chqr-status").textContent = "✅ 已确认接入！";
      $("#chqr-status").style.color = "#16a34a";
      loadChannels();
      setTimeout(() => closeChannelQr(), 1200);
    } else if (s.status === "expired") {
      clearInterval(currentQrPollTimer);
      currentQrPollTimer = null;
      $("#chqr-status").textContent = "⏰ 二维码已过期，请点「刷新二维码」";
      $("#chqr-status").style.color = "#dc2626";
    }
  }, 2000);
}

function closeChannelQr() {
  if (currentQrPollTimer) { clearInterval(currentQrPollTimer); currentQrPollTimer = null; }
  currentQrGenerating = false;
  const refreshBtn = document.querySelector("#channel-qr-modal .ch-btn[onclick*='openChannelQr']");
  if (refreshBtn) refreshBtn.disabled = false;
  $("#channel-qr-modal").style.display = "none";
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
      const lastCheck = fmtTime(status.last_check);
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
      const time = fmtTime(h.time);
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
let _wfExecTimer = null; // 执行记录 running 自动刷新定时器

// 画布平移与缩放
let wfCanvasPan = { x: 0, y: 0, scale: 1 };
let wfCanvasPanning = false;
let wfCanvasPanStart = { x: 0, y: 0 };
let wfPage = 1;
const wfPageSize = 20;
const MIN_SCALE = 0.25;
const MAX_SCALE = 2;

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
    const timeStr = wf.updated_at ? fmtTime(wf.updated_at) : "";
    const createdStr = wf.created_at ? fmtTime(wf.created_at, false) : "";
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
  
  // 自动定位到节点区域中心，确保节点可见
  requestAnimationFrame(() => {
    const nodes = currentWorkflow.nodes || [];
    if (nodes.length) {
      const cx = nodes.reduce((s, n) => s + (n.x || 0), 0) / nodes.length;
      const cy = nodes.reduce((s, n) => s + (n.y || 0), 0) / nodes.length;
      const c = $("#wf-canvas-container");
      if (c) c.scrollTo(Math.max(0, cx - c.clientWidth / 2 + 90), Math.max(0, cy - c.clientHeight / 2));
    }
  });
  
  // 如果测试面板是打开的，刷新输入字段
  if (testPanelOpen) initTestPanel();
}

// 切换视图
function switchWfView(view) {
  currentWfView = view;
  if (_wfExecTimer) { clearTimeout(_wfExecTimer); _wfExecTimer = null; }
  $("#wf-list-view").style.display = view === "list" ? "block" : "none";
  $("#wf-editor-view").style.display = view === "editor" ? "block" : "none";
  $("#wf-templates-view").style.display = view === "templates" ? "block" : "none";
  $$(".wf-view-btn").forEach(btn => btn.classList.toggle("active", btn.dataset.view === view));
  
  if (view === "list") loadWorkflowList();
  if (view === "executions") loadWorkflowExecutions();
}

// 加载工作流执行记录（渲染到列表容器）
async function loadWorkflowExecutions() {
  if (_wfExecTimer) { clearTimeout(_wfExecTimer); _wfExecTimer = null; }
  const container = $("#wf-list-content");
  const cardHtml = allWorkflows.reduce((m, wf) => { m[wf.id] = wf.name; return m; }, {});
  try {
    const execs = await api("/api/workflow/executions?limit=50");
    if (!container) return;
    if (!execs.length) {
      container.innerHTML = `<div style="text-align:center; padding:40px 20px;">
        <div style="font-size:48px; margin-bottom:16px;">📭</div>
        <h3 style="margin:0 auto 8px; color:var(--chat-text);">暂无执行记录</h3>
        <p style="color:var(--text-muted); margin:0;">运行过工作流后，这里会展示执行结果与耗时</p>
      </div>`;
      return;
    }
    let html = '<div class="wf-card-grid">';
    for (const ex of execs) {
      const wfName = cardHtml[ex.workflow_id] || esc(ex.workflow_id);
      const status = ex.status === "completed" ? "✅ 成功" : (ex.status === "running" ? "⏳ 运行中" : "❌ 失败");
      const stClass = ex.status === "completed" ? "wf-status-ok" : (ex.status === "running" ? "wf-status-none" : "wf-status-fail");
      const t = ex.started_at ? fmtTime(ex.started_at) : "";
      const dur = ex.duration_ms ? (ex.duration_ms / 1000).toFixed(1) + "s" : "-";
      const tokens = ex.tokens_used ? String(ex.tokens_used) : "";
      const out = ex.output ? String(ex.output).slice(0, 60) : (ex.error || "");
      html += `<div class="wf-card">
        <div class="wf-card-header"><div class="wf-card-icon">🕘</div><div class="wf-card-name" style="font-weight:600; font-size:13px;">${esc(wfName)}</div></div>
        <div class="wf-card-desc" style="white-space:pre-wrap; color:var(--text-muted);">${esc(out) || "（无输出）"}</div>
        <div class="wf-card-meta"><span class="${stClass}">${status}</span><span>耗时 ${dur}${tokens ? " · ⚡" + tokens + " tokens" : ""}</span></div>
        <div class="wf-card-footer" style="display:flex; justify-content:space-between; align-items:center; gap:6px;">
          <span class="wf-card-time">${t}</span>
          <span style="display:flex; gap:6px;">
            <button class="wf-card-btn" onclick="showWfExecDetail('${ex.id}', this)">📄 详情</button>
            ${ex.status !== "running" ? `<button class="wf-card-btn" onclick="rerunWorkflowExec('${ex.workflow_id}')">▶ 重跑</button>` : ""}
          </span>
        </div>
      </div>
      <div class="wf-exec-detail" id="wfexec-${ex.id}" style="display:none;"></div>`;
    }
    html += '</div>';
    container.innerHTML = html;
    // 若存在运行中的执行记录，4 秒后自动刷新
    if (execs.some((e) => e.status === "running")) {
      _wfExecTimer = setTimeout(() => { _wfExecTimer = null; loadWorkflowExecutions(); }, 4000);
    }
  } catch (e) {
    if (container) container.innerHTML = `<p style="font-size:12px;color:#dc2626;padding:16px;">加载失败: ${esc(e.message || e)}</p>`;
  }
}

// 展开/收起某条执行记录的详情
async function showWfExecDetail(eid, btn) {
  const panel = document.getElementById("wfexec-" + eid);
  if (!panel) return;
  if (panel.style.display === "block") {
    panel.style.display = "none";
    if (btn) btn.textContent = "📄 详情";
    return;
  }
  panel.style.display = "block";
  if (btn) btn.textContent = "📄 收起";
  if (panel.getAttribute("data-loaded")) return;
  try {
    const ex = await api("/api/workflow/executions/" + eid);
    panel.setAttribute("data-loaded", "1");
    const parts = [];
    const box = (label, body) =>
      `<div style="margin-bottom:10px;">
        <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px;">${label}</div>
        <div style="background:var(--card-bg);border:1px solid var(--border);border-radius:6px;padding:8px 10px;font-size:12px;white-space:pre-wrap;word-break:break-word;">${body}</div>
      </div>`;
    if (ex.input !== undefined && ex.input !== null) {
      parts.push(box("输入 input", esc(typeof ex.input === "string" ? ex.input : JSON.stringify(ex.input, null, 2))));
    }
    // 节点观测（各节点请求/响应/耗时）
    if (ex.nodes_status && Object.keys(ex.nodes_status).length) {
      let nh = "";
      for (const [nid, ns] of Object.entries(ex.nodes_status)) {
        const st = ns.status === "ok" ? "✅" : (ns.status === "running" ? "⏳" : "❌");
        const d = ns.duration_ms != null ? (ns.duration_ms / 1000).toFixed(1) + "s" : "-";
        const nm = ns.error ? `<div style="color:#ef4444;margin-top:2px;">${esc(String(ns.error))}</div>` : "";
        nh += `<div style="margin-bottom:6px;">${st} <b>${esc(nid)}</b> · <span class="wf-status-muted">${d}</span>${nm}</div>`;
      }
      parts.push(`<div style="margin-bottom:10px;"><div style="font-size:11px;color:var(--text-muted);margin-bottom:4px;">执行状态 nodes_status</div><div>${nh}</div></div>`);
    }
    if (ex.node_requests && typeof ex.node_requests === "object" && Object.keys(ex.node_requests).length) {
      let rq = "";
      for (const [nid, req] of Object.entries(ex.node_requests)) {
        const resp = (req && req.response !== undefined) ? (typeof req.response === "string" ? req.response : JSON.stringify(req.response, null, 2)) : "";
        const rd = (req && req.duration_ms != null) ? (req.duration_ms / 1000).toFixed(1) + "s" : "";
        rq += `<div style="margin-bottom:8px;">
          <div style="font-size:11px;color:var(--text-muted);">${esc(nid)}${rd ? " · " + rd : ""}</div>
          <div style="background:var(--code-bg);color:var(--code-text);border-radius:5px;padding:6px 8px;font-size:11px;white-space:pre-wrap;word-break:break-word;">${esc(String(resp).slice(0, 800))}</div>
        </div>`;
      }
      parts.push(`<div style="margin-bottom:10px;"><div style="font-size:11px;color:var(--text-muted);margin-bottom:4px;">节点请求/响应 node_requests</div>${rq}</div>`);
    }
    // 输出
    if (ex.output !== undefined && ex.output !== null) {
      parts.push(box("输出 output", esc(typeof ex.output === "string" ? ex.output : JSON.stringify(ex.output, null, 2))));
    }
    // 失败原因
    if (ex.status !== "completed" && ex.error) {
      parts.push(box("失败原因 error", `<span style="color:#ef4444;">${esc(String(ex.error))}</span>`));
    }
    panel.innerHTML = parts.join("") || '<p style="color:var(--text-muted);font-size:12px;">（无更多详情）</p>';
  } catch (e) {
    panel.innerHTML = `<p style="color:#dc2626;font-size:12px;">加载详情失败: ${esc(e.message || e)}</p>`;
  }
}

// 重跑某条执行记录对应的工作流
function rerunWorkflowExec(wfId) {
  runWorkflow(wfId);
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
    path.setAttribute("class", "wf-edge-path");
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
    
    // 端点手柄：可拖动重连
    const handleR = idx === selectedEdgeIdx ? 8 : 6;
    const mkHandle = (hx, hy, kind) => {
      const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      c.setAttribute("cx", hx);
      c.setAttribute("cy", hy);
      c.setAttribute("r", handleR);
      c.setAttribute("fill", idx === selectedEdgeIdx ? "#ef4444" : "var(--card-bg)");
      c.setAttribute("stroke", idx === selectedEdgeIdx ? "#ef4444" : "var(--primary)");
      c.setAttribute("stroke-width", "2");
      c.style.cursor = "crosshair";
      c.style.pointerEvents = "all";
      c.addEventListener("mousedown", (ev) => startEdgeDrag(ev, idx, kind));
      return c;
    };
    svg.appendChild(mkHandle(x1, y1, "source"));
    svg.appendChild(mkHandle(x2, y2, "target"));
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

// 拖动连线端点重连
let wfEdgeDrag = null; // { idx, kind: "source"|"target" }

function startEdgeDrag(e, idx, kind) {
  e.stopPropagation();
  e.preventDefault();
  const edge = currentWorkflow && currentWorkflow.edges[idx];
  if (!edge) return;
  wfEdgeDrag = { idx, kind };
  selectedEdgeIdx = idx;
  
  const svg = $("#wf-canvas-edges");
  const container = $("#wf-canvas-container");
  const cRect = container.getBoundingClientRect();
  
  const tmpLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
  tmpLine.setAttribute("stroke", "var(--primary)");
  tmpLine.setAttribute("stroke-width", "2");
  tmpLine.setAttribute("stroke-dasharray", "6,3");
  tmpLine.style.pointerEvents = "none";
  svg.appendChild(tmpLine);
  
  const getEndPos = () => {
    const sourceNode = currentWorkflow.nodes.find(n => n.id === edge.source);
    const targetNode = currentWorkflow.nodes.find(n => n.id === edge.target);
    return {
      sx: sourceNode.x + 180, sy: sourceNode.y + 28,
      tx: targetNode.x, ty: targetNode.y + 28
    };
  };
  
  const onMove = (ev) => {
    const cx = ev.clientX - cRect.left + container.scrollLeft;
    const cy = ev.clientY - cRect.top + container.scrollTop;
    const p = getEndPos();
    if (kind === "source") {
      tmpLine.setAttribute("x1", cx); tmpLine.setAttribute("y1", cy);
      tmpLine.setAttribute("x2", p.tx); tmpLine.setAttribute("y2", p.ty);
    } else {
      tmpLine.setAttribute("x1", p.sx); tmpLine.setAttribute("y1", p.sy);
      tmpLine.setAttribute("x2", cx); tmpLine.setAttribute("y2", cy);
    }
  };
  
  const onUp = (ev) => {
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
    if (tmpLine && tmpLine.parentNode) tmpLine.remove();
    const edgeNow = currentWorkflow.edges[idx];
    if (edgeNow) {
      // elementsFromPoint：穿透手柄/连线找端口
      const els = document.elementsFromPoint(ev.clientX, ev.clientY);
      const port = els.find(el => el.classList && (el.classList.contains("wf-port-in") || el.classList.contains("wf-port-out")));
      if (port) {
        const pid = port.dataset.id;
        if (kind === "source" && port.classList.contains("wf-port-out") && pid !== edgeNow.target) {
          edgeNow.source = pid;
          renderEdges();
        } else if (kind === "target" && port.classList.contains("wf-port-in") && pid !== edgeNow.source) {
          edgeNow.target = pid;
          renderEdges();
        }
      }
    }
    wfEdgeDrag = null;
  };
  
  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);
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
    if (n.type === "loop") {
      vars.add(n.config?.item_variable || "item");
      vars.add(n.config?.index_variable || "index");
      vars.add(n.id + "_results");
    }
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
          <select class="ncf-select" id="ncf-llm-model-select" onchange="updateNodeConfig('model', this.value)" style="flex:1;">
            <option value="">加载中...</option>
          </select>
          <button class="btn-test" onclick="refreshCloudModels()" style="white-space:nowrap; font-size:12px;">🔄 刷新</button>
        </div>
        <div id="ncf-llm-model-info" style="margin-top:4px; font-size:11px; color:var(--text-muted);"></div></div>
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
    case "iteration":
      html += `<div class="ncf-section"><div class="ncf-group-title">遍历配置</div>
        <div class="ncf-row"><label class="ncf-label">遍历数组</label><input class="ncf-input" value="${esc(cfg.array_variable||'{{input}}')}" onchange="updateNodeConfig('array_variable',this.value)"></div>
        <div class="ncf-row"><label class="ncf-label">项变量名</label><input class="ncf-input" value="${esc(cfg.item_variable||'item')}" onchange="updateNodeConfig('item_variable',this.value)"></div></div>`;
      break;
    case "kb_index":
      html += `<div class="ncf-section"><div class="ncf-group-title">知识入库</div>
        <div class="ncf-row"><label class="ncf-label">目标知识库</label><input class="ncf-input" value="${esc(cfg.kb_id||'default')}" onchange="updateNodeConfig('kb_id',this.value)"></div>
        <div class="ncf-row"><label class="ncf-label">文档标题</label><input class="ncf-input" value="${esc(cfg.title||'')}" placeholder="默认 workflow_节点id" onchange="updateNodeConfig('title',this.value)"></div>
        <div class="ncf-row"><label class="ncf-label">入库内容</label><textarea class="ncf-input" rows="3" onchange="updateNodeConfig('content',this.value)">${esc(cfg.content||'{{input}}')}</textarea></div>
        <div class="ncf-row"><label class="ncf-label">模式</label><select class="ncf-input" onchange="updateNodeConfig('mode',this.value)"><option value="append" ${(cfg.mode||'append')==='append'?'selected':''}>追加</option><option value="replace" ${cfg.mode==='replace'?'selected':''}>替换</option></select></div></div>`;
      break;
    case "memory_read":
      html += `<div class="ncf-section"><div class="ncf-group-title">记忆读取</div>
        <div class="ncf-row"><label class="ncf-label">记忆键</label><input class="ncf-input" value="${esc(cfg.memory_key||'{{input}}')}" onchange="updateNodeConfig('memory_key',this.value)"></div>
        <div class="ncf-row"><label class="ncf-label">命名空间</label><input class="ncf-input" value="${esc(cfg.namespace||'default')}" onchange="updateNodeConfig('namespace',this.value)"></div></div>`;
      break;
    case "memory_write":
      html += `<div class="ncf-section"><div class="ncf-group-title">记忆写入</div>
        <div class="ncf-row"><label class="ncf-label">记忆键</label><input class="ncf-input" value="${esc(cfg.memory_key||'')}" onchange="updateNodeConfig('memory_key',this.value)"></div>
        <div class="ncf-row"><label class="ncf-label">内容</label><textarea class="ncf-input" rows="2" onchange="updateNodeConfig('content',this.value)">${esc(cfg.content||'{{input}}')}</textarea></div>
        <div class="ncf-row"><label class="ncf-label">命名空间</label><input class="ncf-input" value="${esc(cfg.namespace||'default')}" onchange="updateNodeConfig('namespace',this.value)"></div></div>`;
      break;
    case "memory_clear":
      html += `<div class="ncf-section"><div class="ncf-group-title">记忆清除</div>
        <div class="ncf-row"><label class="ncf-label">命名空间</label><input class="ncf-input" value="${esc(cfg.namespace||'default')}" onchange="updateNodeConfig('namespace',this.value)"></div></div>`;
      break;
    case "mcp_call":
      html += `<div class="ncf-section"><div class="ncf-group-title">MCP 调用</div>
        <div class="ncf-row"><label class="ncf-label">MCP 服务器</label><input class="ncf-input" id="ncf-mcp-server" value="${esc(cfg.mcp_server||'')}" placeholder="服务器ID或名称" onchange="updateNodeConfig('mcp_server',this.value)"></div>
        <div class="ncf-row"><label class="ncf-label">工具名</label><input class="ncf-input" value="${esc(cfg.tool_name||'')}" onchange="updateNodeConfig('tool_name',this.value)"></div>
        <div class="ncf-row"><label class="ncf-label">参数 JSON</label><textarea class="ncf-input" rows="3" onchange="updateNodeConfig('arguments',this.value)">${esc(cfg.arguments||'{}')}</textarea></div></div>`;
      setTimeout(loadMcpServerOptions, 100);
      break;
    case "json_parse":
      html += `<div class="ncf-section"><div class="ncf-group-title">JSON 解析</div>
        <div class="ncf-row"><label class="ncf-label">输入 JSON</label><textarea class="ncf-input" rows="3" onchange="updateNodeConfig('input',this.value)">${esc(cfg.input||'{{input}}')}</textarea></div>
        <div class="ncf-hint">解析结果会展开为变量，可通过 {{字段名}} 引用</div></div>`;
      break;
    case "email":
      html += `<div class="ncf-section"><div class="ncf-group-title">发送邮件</div>
        <div class="ncf-row"><label class="ncf-label">收件人</label><input class="ncf-input" value="${esc(cfg.to||'')}" placeholder="a@b.com, c@d.com" onchange="updateNodeConfig('to',this.value)"></div>
        <div class="ncf-row"><label class="ncf-label">主题</label><input class="ncf-input" value="${esc(cfg.subject||'')}" onchange="updateNodeConfig('subject',this.value)"></div>
        <div class="ncf-row"><label class="ncf-label">正文</label><textarea class="ncf-input" rows="3" onchange="updateNodeConfig('body',this.value)">${esc(cfg.body||'')}</textarea></div>
        <div class="ncf-hint">需先在设置中配置 SMTP 邮箱</div></div>`;
      break;
    case "webhook":
      html += `<div class="ncf-section"><div class="ncf-group-title">Webhook 回调</div>
        <div class="ncf-row"><label class="ncf-label">URL</label><input class="ncf-input" value="${esc(cfg.url||'')}" onchange="updateNodeConfig('url',this.value)"></div>
        <div class="ncf-row-inline"><div><label class="ncf-label">方法</label><select class="ncf-input" onchange="updateNodeConfig('method',this.value)"><option value="POST" ${(cfg.method||'POST')==='POST'?'selected':''}>POST</option><option value="GET" ${cfg.method==='GET'?'selected':''}>GET</option><option value="PUT" ${cfg.method==='PUT'?'selected':''}>PUT</option></select></div></div>
        <div class="ncf-row"><label class="ncf-label">Body</label><textarea class="ncf-input" rows="2" onchange="updateNodeConfig('body',this.value)">${esc(cfg.body||'')}</textarea></div></div>`;
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
  const sel = $("#ncf-llm-model-select");
  const info = $("#ncf-llm-model-info");
  if (!sel) return;
  sel.innerHTML = '<option value="">加载中...</option>';
  try {
    const providers = await api("/api/providers");
    const models = [];
    providers.forEach(p => {
      if (p.enabled === false) return;
      (p.models || []).forEach(m => {
        const name = (m || '').toLowerCase();
        const isFree = name.endsWith('-free') || name === 'big-pickle'
          || ['flash', 'mini', 'lite', 'tiny', 'small', 'nano'].some(k => name.includes('-'+k))
          || p.default_model === m && (p.type || '').includes('free');
        models.push({ model: m, provider: p.name || p.id, isFree });
      });
    });
    if (models.length) {
      const node = currentWorkflow?.nodes.find(n => n.id === selectedNode);
      const currentModel = node?.config?.model || '';
      // 默认按该供应商配置的默认模型
      let defaultModel = '';
      const enabledP = providers.find(p => (p.default_model || '') && p.enabled !== false);
      if (enabledP) defaultModel = enabledP.default_model;
      const opts = models.map(m =>
        `<option value="${esc(m.model)}" ${m.model===currentModel||(!currentModel&&m.model===defaultModel)?'selected':''}>${m.isFree?'🆓':'💰'} ${esc(m.model)} · ${esc(m.provider)}</option>`
      ).join('');
      sel.innerHTML = opts;
      const freeCount = models.filter(m=>m.isFree).length;
      const curFree = models.some(m=>m.model===(currentModel||defaultModel) && m.isFree);
      if (info) info.innerHTML = `<span style="font-size:11px; color:var(--text-muted);">共 ${models.length} 个模型 · ${freeCount} 个免费 🆓</span>` +
        (curFree ? ` <span style="color:var(--accent,#22c55e); font-weight:600;">✅ 当前为免费模型，无需 API Key</span>` : ` <span style="color:#eab308;">⚠ 默认模型需 Key</span>`);
      // 自动应用默认模型到节点配置（未指定时）
      if (!currentModel && defaultModel) updateNodeConfig('model', defaultModel);
    } else {
      sel.innerHTML = '<option value="">未配置供应商，请先在设置中添加</option>';
      if (info) info.textContent = '⚠ 请先在「设置 › 模型供应商」中添加并启用供应商';
    }
  } catch (e) {
    sel.innerHTML = '<option value="">加载失败</option>';
    if (info) info.textContent = '❌ ' + e.message;
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

// 加载 MCP 服务器下拉选项
async function loadMcpServerOptions() {
  const input = $("#ncf-mcp-server");
  if (!input) return;
  try {
    const mcps = await api("/api/mcp/servers");
    if (!mcps || !mcps.length) return;
    const cur = input.value;
    const opts = mcps.map(m => `<option value="${esc(m.id)}" ${m.id===cur||m.name===cur?'selected':''}>${esc(m.name||m.id)}</option>`).join("");
    input.outerHTML = `<select class="ncf-input" id="ncf-mcp-server" onchange="updateNodeConfig('mcp_server',this.value)"><option value="">选择服务器...</option>${opts}</select>`;
  } catch (e) { /* 忽略，保留文本输入 */ }
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
    case "llm": return { prompt: "", model: "", model_source: "local", system: "", temperature: 0.7, memory_mode: "none", output_variable: "", retry: false };
    case "kb_search": return { query: "{{input}}", top_k: 5, kb_id: "", threshold: 0, output_variable: "" };
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
      const timeStr = exec.started_at ? fmtTime(exec.started_at) : "";
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

// ===== 工作流测试面板（百炼风格） =====
let wfTestFiles = [];
let wfTestVars = [];
let testPanelOpen = false;
let wfTestHistory = [];
let wfExpConfig = { welcome: "", presetQuestions: [], testSamples: [] };

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
  const fileEl = $("#wf-test-file-list");
  if (fileEl) fileEl.innerHTML = "";
  // 显示工作流名称
  const nameEl = $("#wf-test-wf-name");
  if (nameEl) nameEl.textContent = currentWorkflow.name || "工作流测试";
  // 显示空状态
  const emptyEl = $("#wf-test-empty");
  const msgsEl = $("#wf-test-messages");
  if (emptyEl) emptyEl.style.display = "block";
  if (msgsEl) { msgsEl.style.display = "none"; msgsEl.innerHTML = ""; }
  wfTestHistory = [];
  // 自动聚焦输入框
  const input = $("#wf-test-input");
  if (input) { input.value = ""; input.focus(); updateSendBtnState(); }
}

function updateSendBtnState() {
  const input = $("#wf-test-input");
  const btn = $("#wf-test-send-btn");
  if (!input || !btn) return;
  const hasText = input.value.trim().length > 0;
  const hasFiles = wfTestFiles.length > 0;
  if (hasText || hasFiles) {
    btn.style.background = "#f97316";
    btn.style.color = "white";
    btn.style.cursor = "pointer";
  } else {
    btn.style.background = "#e5e7eb";
    btn.style.color = "#9ca3af";
    btn.style.cursor = "not-allowed";
  }
}

function handleWfTestFiles(fileList) {
  if (!fileList || !fileList.length) return;
  const MAX_FILES = 5;
  for (const f of Array.from(fileList)) {
    if (wfTestFiles.length >= MAX_FILES) {
      alert("最多同时上传 5 个附件");
      break;
    }
    if (f.size > 20 * 1024 * 1024) {
      alert(`文件过大（>20MB）：${f.name}`);
      continue;
    }
    wfTestFiles.push(f);
  }
  renderWfTestFileList();
  updateSendBtnState();
}

function renderWfTestFileList() {
  const fileEl = $("#wf-test-file-list");
  if (!fileEl) return;
  fileEl.innerHTML = "";
  wfTestFiles.forEach((f, idx) => {
    const chip = document.createElement("span");
    chip.className = "wf-test-file-chip";
    chip.innerHTML = `📎 ${esc(f.name)} <span class="wf-test-file-x" data-idx="${idx}" title="移除">✕</span>`;
    chip.querySelector(".wf-test-file-x").addEventListener("click", () => {
      wfTestFiles.splice(idx, 1);
      renderWfTestFileList();
      updateSendBtnState();
    });
    fileEl.appendChild(chip);
  });
}

function appendWfTestMsg(role, content, nodeResults) {
  const msgsEl = $("#wf-test-messages");
  if (!msgsEl) return;
  const isUser = role === "user";
  const avatar = isUser ? "U" : "A";
  let nodeHtml = "";
  if (nodeResults && nodeResults.length > 0) {
    nodeHtml = '<div style="margin-top:8px; padding-top:8px; border-top:1px solid #f0f0f0;">' +
      nodeResults.map(nr => {
        const ic = getNodeIcon(nr.type || "");
        const cls = nr.status === "completed" ? "completed" : nr.status === "failed" ? "failed" : "running";
        const si = nr.status === "completed" ? "✅" : nr.status === "failed" ? "❌" : "⏳";
        return `<div class="wf-node-status ${cls}">${si} ${ic} ${esc(nr.label || nr.node_id)} ${nr.duration_ms ? nr.duration_ms + 'ms' : ''}</div>`;
      }).join('') + '</div>';
  }
  msgsEl.style.display = "block";
  const emptyEl = $("#wf-test-empty");
  if (emptyEl) emptyEl.style.display = "none";
  const html = `<div class="wf-msg ${role}">
    <div class="wf-msg-avatar">${avatar}</div>
    <div class="wf-msg-bubble">${content}${nodeHtml}</div>
  </div>`;
  msgsEl.insertAdjacentHTML("beforeend", html);
  msgsEl.scrollTop = msgsEl.scrollHeight;
}

function clearWfTestHistory() {
  wfTestHistory = [];
  const msgsEl = $("#wf-test-messages");
  const emptyEl = $("#wf-test-empty");
  if (msgsEl) { msgsEl.innerHTML = ""; msgsEl.style.display = "none"; }
  if (emptyEl) emptyEl.style.display = "block";
}

async function executeWfTestFromInput() {
  const input = $("#wf-test-input");
  if (!input) return;
  const text = input.value.trim();
  if (!text && wfTestFiles.length === 0) return;
  if (!currentWorkflow || !currentWorkflow.id) { alert("请先保存工作流"); return; }
  // 显示用户消息
  const displayText = text || "(附件)";
  appendWfTestMsg("user", esc(displayText));
  input.value = "";
  updateSendBtnState();
  // 执行测试
  await executeWfTestWithMessage(text);
}

async function executeWfTestWithMessage(text) {
  // 收集输入
  const startNode = currentWorkflow.nodes.find(n => n.type === "start");
  const fields = (startNode?.config?.input_fields) || ["input"];
  const inputData = {};
  if (fields.length === 1) {
    inputData[fields[0]] = text;
  } else {
    fields.forEach(f => { inputData[f] = text; });
  }
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
  wfTestFiles = [];
  const fileEl = $("#wf-test-file-list");
  if (fileEl) fileEl.innerHTML = "";
  // 显示思考中
  const thinkingId = "thinking-" + Date.now();
  const msgsEl = $("#wf-test-messages");
  msgsEl.insertAdjacentHTML("beforeend", `<div class="wf-msg assistant" id="${thinkingId}">
    <div class="wf-msg-avatar">A</div>
    <div class="wf-msg-bubble"><span class="typing-indicator"><span></span><span></span><span></span></span></div>
  </div>`);
  msgsEl.scrollTop = msgsEl.scrollHeight;
  try {
    const body = { input: inputData };
    if (attachments.length > 0) body.attachments = attachments;
    const resp = await fetch(`/api/workflows/${currentWorkflow.id}/run_stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const thinkingEl = $("#" + thinkingId);
    if (!resp.ok) {
      const result = await api(`/api/workflows/${currentWorkflow.id}/run`, {
        method: "POST", body: JSON.stringify(body),
      });
      if (thinkingEl) thinkingEl.remove();
      if (result.success) {
        const nodeResults = Object.values(result.node_results || {}).map(nr => ({
          node_id: nr.node_id, type: nr.type, label: nr.label, status: nr.status, duration_ms: nr.duration_ms
        }));
        appendWfTestMsg("assistant", `<pre style="margin:0; white-space:pre-wrap;">${esc(result.output || "")}</pre>`, nodeResults);
      } else {
        appendWfTestMsg("assistant", `<span style="color:#dc2626;">❌ ${esc(result.error || "运行失败")}</span>`);
      }
    } else {
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "", streamOutput = "", nodeEvents = [];
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
              if (thinkingEl) {
                thinkingEl.querySelector(".wf-msg-bubble").innerHTML = `<pre style="margin:0; white-space:pre-wrap;">${esc(streamOutput)}</pre>`;
                msgsEl.scrollTop = msgsEl.scrollHeight;
              }
            } else if (evt.type === "node_status" && evt.data) {
              nodeEvents.push(evt.data);
            } else if (evt.done) {
              if (thinkingEl) thinkingEl.remove();
              appendWfTestMsg("assistant", `<pre style="margin:0; white-space:pre-wrap;">${esc(evt.output || streamOutput)}</pre>`, nodeEvents);
            } else if (evt.error) {
              if (thinkingEl) thinkingEl.remove();
              appendWfTestMsg("assistant", `<span style="color:#dc2626;">❌ ${esc(evt.error)}</span>`);
            }
          } catch(e) {}
        }
      }
    }
  } catch (e) {
    const thinkingEl = $("#" + thinkingId);
    if (thinkingEl) thinkingEl.remove();
    appendWfTestMsg("assistant", `<span style="color:#dc2626;">❌ ${esc(e.message)}</span>`);
  }
}

// 入参参数配置
function openWfInputConfig() {
  const startNode = currentWorkflow?.nodes.find(n => n.type === "start");
  const fields = (startNode?.config?.input_fields) || ["input"];
  const html = `<div class="wf-config-modal open" id="wf-input-config-modal">
    <div class="wf-config-header">
      <h3>入参变量配置</h3>
      <button onclick="closeWfInputConfig()" style="width:28px;height:28px;border:none;border-radius:6px;background:transparent;color:#6b7280;cursor:pointer;font-size:18px;">✕</button>
    </div>
    <div class="wf-config-body">
      <div style="margin-bottom:16px;">
        <div style="font-size:13px;font-weight:600;color:#374151;margin-bottom:8px;">内置变量</div>
        ${fields.map(f => `<div style="padding:12px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;margin-bottom:8px;">
          <div style="font-size:13px;font-weight:500;color:#1f2937;">${esc(f)} <span style="color:#6b7280;font-size:12px;">[string]</span></div>
          <div style="font-size:12px;color:#6b7280;margin-top:4px;">用于传递输入参数</div>
        </div>`).join('')}
      </div>
      <div style="margin-bottom:16px;">
        <div style="font-size:13px;font-weight:600;color:#374151;margin-bottom:8px;">自定义变量</div>
        <div id="wf-input-custom-vars"></div>
        <button onclick="addWfInputCustomVar()" style="padding:8px 16px;border:1px dashed #d1d5db;border-radius:8px;background:transparent;color:#6b7280;cursor:pointer;font-size:13px;width:100%;margin-top:8px;">+ 添加变量</button>
      </div>
    </div>
    <div class="wf-config-footer">
      <button onclick="closeWfInputConfig()" style="padding:8px 16px;border:1px solid #e5e7eb;border-radius:8px;background:white;color:#374151;cursor:pointer;font-size:13px;">取消</button>
      <button onclick="saveWfInputConfig()" style="padding:8px 16px;border:none;border-radius:8px;background:#667eea;color:white;cursor:pointer;font-size:13px;font-weight:500;">确认</button>
    </div>
  </div>`;
  document.body.insertAdjacentHTML("beforeend", html);
}

function closeWfInputConfig() {
  const el = $("#wf-input-config-modal");
  if (el) el.remove();
}

function addWfInputCustomVar() {
  const container = $("#wf-input-custom-vars");
  if (!container) return;
  const id = "cvar_" + Date.now();
  container.insertAdjacentHTML("beforeend", `<div style="display:flex;gap:8px;margin-bottom:8px;" id="${id}">
    <input placeholder="变量名" style="flex:1;padding:8px;border:1px solid #e5e7eb;border-radius:6px;font-size:13px;">
    <input placeholder="默认值" style="flex:1;padding:8px;border:1px solid #e5e7eb;border-radius:6px;font-size:13px;">
    <button onclick="$('#${id}').remove()" style="width:32px;height:32px;border:none;border-radius:6px;background:transparent;color:#ef4444;cursor:pointer;">✕</button>
  </div>`);
}

function saveWfInputConfig() {
  closeWfInputConfig();
}

// 体验配置
function openWfExpConfig() {
  const html = `<div class="wf-config-modal open" id="wf-exp-config-modal">
    <div class="wf-config-header">
      <h3>体验配置：文本对话</h3>
      <button onclick="closeWfExpConfig()" style="width:28px;height:28px;border:none;border-radius:6px;background:transparent;color:#6b7280;cursor:pointer;font-size:18px;">✕</button>
    </div>
    <div class="wf-config-body">
      <div style="margin-bottom:20px;">
        <div style="font-size:13px;font-weight:600;color:#374151;margin-bottom:8px;">欢迎语</div>
        <textarea id="wf-exp-welcome" rows="4" placeholder="请输入欢迎语" style="width:100%;padding:10px;border:1px solid #e5e7eb;border-radius:8px;font-size:13px;resize:vertical;font-family:inherit;">${esc(wfExpConfig.welcome)}</textarea>
        <div style="text-align:right;font-size:11px;color:#9ca3af;margin-top:4px;">${wfExpConfig.welcome.length} / 200</div>
      </div>
      <div style="margin-bottom:20px;">
        <div style="font-size:13px;font-weight:600;color:#374151;margin-bottom:4px;">预设问题(${wfExpConfig.presetQuestions.length}/5)</div>
        <div style="font-size:12px;color:#6b7280;margin-bottom:8px;">暂无预设问题，点击按钮添加</div>
        <div id="wf-exp-questions">${wfExpConfig.presetQuestions.map((q, i) => `<div style="display:flex;gap:8px;margin-bottom:8px;">
          <input value="${esc(q)}" onchange="wfExpConfig.presetQuestions[${i}]=this.value" style="flex:1;padding:8px;border:1px solid #e5e7eb;border-radius:6px;font-size:13px;">
          <button onclick="wfExpConfig.presetQuestions.splice(${i},1);openWfExpConfig()" style="width:32px;height:32px;border:none;border-radius:6px;background:transparent;color:#ef4444;cursor:pointer;">✕</button>
        </div>`).join('')}</div>
        <button onclick="addWfExpQuestion()" style="padding:8px 16px;border:1px dashed #d1d5db;border-radius:8px;background:transparent;color:#6b7280;cursor:pointer;font-size:13px;">+ 添加问题</button>
      </div>
      <div>
        <div style="font-size:13px;font-weight:600;color:#374151;margin-bottom:4px;">测试样例(${wfExpConfig.testSamples.length}/10)</div>
        <div style="font-size:12px;color:#6b7280;margin-bottom:8px;">预置一组输入数据，配置完成后可快速发起测试。暂无测试样例，点击按钮添加</div>
        <div id="wf-exp-samples">${wfExpConfig.testSamples.map((s, i) => `<div style="display:flex;gap:8px;margin-bottom:8px;">
          <input value="${esc(s)}" onchange="wfExpConfig.testSamples[${i}]=this.value" style="flex:1;padding:8px;border:1px solid #e5e7eb;border-radius:6px;font-size:13px;">
          <button onclick="wfExpConfig.testSamples.splice(${i},1);openWfExpConfig()" style="width:32px;height:32px;border:none;border-radius:6px;background:transparent;color:#ef4444;cursor:pointer;">✕</button>
        </div>`).join('')}</div>
        <button onclick="addWfExpSample()" style="padding:8px 16px;border:1px dashed #d1d5db;border-radius:8px;background:transparent;color:#6b7280;cursor:pointer;font-size:13px;">+ 添加样例</button>
      </div>
    </div>
    <div class="wf-config-footer">
      <button onclick="closeWfExpConfig()" style="padding:8px 16px;border:1px solid #e5e7eb;border-radius:8px;background:white;color:#374151;cursor:pointer;font-size:13px;">取消</button>
      <button onclick="saveWfExpConfig()" style="padding:8px 16px;border:none;border-radius:8px;background:#667eea;color:white;cursor:pointer;font-size:13px;font-weight:500;">确认</button>
    </div>
  </div>`;
  document.body.insertAdjacentHTML("beforeend", html);
}

function closeWfExpConfig() {
  const el = $("#wf-exp-config-modal");
  if (el) el.remove();
}

function addWfExpQuestion() {
  if (wfExpConfig.presetQuestions.length >= 5) return;
  wfExpConfig.presetQuestions.push("");
  closeWfExpConfig();
  openWfExpConfig();
}

function addWfExpSample() {
  if (wfExpConfig.testSamples.length >= 10) return;
  wfExpConfig.testSamples.push("");
  closeWfExpConfig();
  openWfExpConfig();
}

function saveWfExpConfig() {
  const welcomeEl = $("#wf-exp-welcome");
  if (welcomeEl) wfExpConfig.welcome = welcomeEl.value;
  closeWfExpConfig();
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
  follow();
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
  follow();
}

// 工具结果：不仅更新状态头，还用 HTML 渲染实际返回内容到卡片体内
function setToolResult(card, ok, statusText, resultHtml) {
  const head = card.querySelector(".tool-status");
  head.textContent = statusText || (ok ? "✅ 完成" : "❌ 失败");
  head.className = "tool-status " + (ok ? "ok" : "err");
  const resultPre = card.querySelector(".tool-result");
  if (resultPre) {
    // 用 innerHTML 渲染组装好的结果块（长度超限时自动折叠）
    resultPre.innerHTML = resultHtml;
  }
  card.classList.remove("open");
  follow();
}

// ===== 发送：队列 / 抢断 / 自动压缩 =====
let sendQueue = [];
let queueSeq = 0;

async function sendMessage() {
  const input = $("#chat-input");
  const text = input.value.trim();
  if (!text && !pendingAttachments.length) return;
  if (state.streaming) {
    // 直接排队，无弹窗限制
    sendQueue.push({ id: ++queueSeq, text, attachFiles: pendingAttachments.length ? [...pendingAttachments] : null });
    if (pendingAttachments.length) { pendingAttachments = []; renderAttachPreview(); }
    renderQueue();
    $("#chat-input").value = "";
    autoResize();
    return;
  }
  await doSend(text);
}

async function doSend(text, attachFiles = null) {
  const userMsg = text; // 保存用户消息用于生成建议
  const input = $("#chat-input");
  if (!state.currentConvId) {
    const data = await api("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ title: text.slice(0, 30) || "新对话", model: state.currentModel }),
    });
    state.currentConvId = data.id;
    await loadConvs();
    selectConv(data.id);
  }

  // 上传附件（优先用传入的排队附件）
  let attachments = [];
  if (attachFiles && attachFiles.length) {
    pendingAttachments = attachFiles;
    renderAttachPreview();
    attachments = await uploadAttachments();
  } else if (pendingAttachments.length) {
    attachments = await uploadAttachments();
  }

  const indicator = $("#streaming-indicator");
  const indicatorText = $("#streaming-text");

  // 获取历史 + 超长时自动压缩（保留最近 6 条 + 摘要）
  const history = await api(`/api/conversations/${state.currentConvId}/messages`);
  let hist = history.map((m) => ({ role: m.role, content: m.content }));
  const KEEP = 6;
  if (hist.length > 12) {
    const oldMsgs = hist.slice(0, hist.length - KEEP);
    const recentMsgs = hist.slice(hist.length - KEEP);
    try {
      indicator.classList.add("visible");
      indicatorText.textContent = "正在压缩上下文...";
      const summary = await compressMessages(oldMsgs);
      hist = [{ role: "system", content: "以下是此前对话的压缩摘要：\n" + summary }].concat(recentMsgs);
    } catch (e) {
      // 压缩失败则退回截断策略，不阻塞发送
      hist = hist.slice(-12);
    } finally {
      indicatorText.textContent = "正在思考...";
    }
  }

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
  indicator.classList.add("visible");
  indicatorText.textContent = "正在思考...";

  let acc = "";
  const holder = document.createElement("div");
  holder.className = "msg assistant streaming";
  holder.innerHTML = `<div class="avatar">AB</div><div class="bubble"></div>`;
  $("#messages").appendChild(holder);

  const controller = new AbortController();
  state.abortController = controller;
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
        kb_id: state.chatKbId || "",
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
          // 智能跟随：在底部才自动滚动；滚离底部则计数并显示「下拉阅读」
          if (_atBottom) {
            scrollBottom();
          } else {
            _pendingNew++;
            syncReadMoreBar();
          }
        } else if (payload.tool_start) {
          currentTool = createToolCard(payload.tool_start.name, payload.tool_start.args);
        } else if (payload.tool_result) {
          if (currentTool) {
            // 在卡片里展示工具实际返回内容（而非仅状态），展开即可看到完整结果
            let resText = typeof payload.tool_result.result === "string"
              ? payload.tool_result.result : JSON.stringify(payload.tool_result.result || {}, null, 2);
            // 结果很长时折叠：卡片里保留前 800 字符，剩余放入 <details>
            const MAX = 800;
            let resultHtml;
            if (resText.length > MAX) {
              resultHtml = `<span class="tool-result-trunc">${esc(resText.slice(0, MAX))}…</span>`
                + `<details class="tool-result-more"><summary>展开完整结果（${resText.length}字符）</summary><pre>${esc(resText)}</pre></details>`;
            } else {
              resultHtml = `<pre class="tool-result-full">${esc(resText)}</pre>`;
            }
            setToolResult(currentTool, payload.tool_result.ok,
              payload.tool_result.ok ? "✅ 完成" : "❌ 失败", resultHtml);
          }
        } else if (payload.error) {
          // 追加错误信息而不是覆盖已生成内容，避免"工具调用后中断/丢失"
          const errEl = document.createElement("div");
          errEl.className = "bubble error";
          errEl.innerHTML = `⚠ ${esc(payload.error)}`;
          holder.querySelector(".bubble").appendChild(errEl);
          done = true;
        } else if (payload.done) {
          done = true;
          // 显示回答来源（知识库引用 + 网页链接），受智能体 show_sources 开关控制
          const sources = payload.sources || [];
          const agentCfg = window._currentAgentCfg || null;
          const showSrc = agentCfg ? agentCfg.show_sources !== false : true;
          const b = holder.querySelector(".bubble");
          if (sources.length > 0 && b && showSrc) {
            const srcHtml = `<div class="agent-sources">📚 回答来源：${sources.map(s => {
              if (s.url) {
                let host = s.url;
                try { host = new URL(s.url).hostname.replace(/^www\./, ''); } catch(e) {}
                return `<a class="source-tag" href="${esc(s.url)}" target="_blank" rel="noopener">🔗 ${esc(host)}</a>`;
              }
              return `<span class="source-tag" title="${esc(s.snippet || '')}">📄 ${esc(s.doc_name || '未知')}${s.score != null ? ` <i>${(s.score * 100).toFixed(0)}%</i>` : ''}</span>`;
            }).join(' ')}</div>`;
            const wrap = document.createElement("div");
            wrap.innerHTML = srcHtml;
            b.appendChild(wrap.firstChild);
          }
          // 回复干预：编辑/修改 AI 回复后重发
          if (acc && b && !acc.includes("⚠")) {
            const editBtn = document.createElement("button");
            editBtn.className = "btn-edit-reply";
            editBtn.innerHTML = "✏️ 干预回复";
            editBtn.title = "把回复放入输入框，修改后重新发送";
            editBtn.onclick = () => {
              const input = $("#chat-input");
              if (input) {
                input.value = acc;
                input.focus();
                if (window.resizeInput) resizeInput(input);
              }
            };
            b.appendChild(editBtn);
          }
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
    state.abortController = null;
    holder.classList.remove("streaming");
    indicator.classList.remove("visible");
    $("#send-btn").style.display = "block";
    $("#stop-btn").style.display = "none";
    loadConvs();
    // 生成提示词建议（不阻塞队列处理）
    if (state.suggestionEnabled && acc && !acc.includes("⚠")) {
      try {
        const suggestions = generateSuggestions(userMsg, acc);
        renderSuggestions(suggestions, "chat-area");
      } catch (e) {
        console.warn("生成提示词建议失败:", e);
      }
    }
    // 记录停止时用户是否已滚离底部，用于收尾时保留阅读位置
    const keepPos = !_atBottom;
    const prevScrollTop = $("#chat-area").scrollTop;
    if (state.currentConvId) {
      try {
        loadMessages(state.currentConvId);
      } catch (e) {
        console.warn("刷新消息列表失败:", e);
      }
    }
    try {
      if (keepPos && !state.streaming) {
        // 用户中途停止且已滚离底部：保留阅读位置不受打扰
        $("#chat-area").scrollTop = prevScrollTop;
        _atBottom = false;
      } else {
        _atBottom = true;
        scrollBottom();
      }
      syncReadMoreBar();
    } catch (e) {
      console.warn("滚动收尾失败:", e);
    }
    // 发送队列中的下一条
    processQueue();
  }
}

// 渲染待发送队列（支持编辑 / 删除）
function renderQueue() {
  const box = $("#send-queue");
  if (!box) return;
  if (!sendQueue.length) {
    box.style.display = "none";
    box.innerHTML = "";
    return;
  }
  box.style.display = "flex";
  box.innerHTML = "";
  sendQueue.forEach((item, idx) => {
    const div = document.createElement("div");
    div.className = "queue-item";
    div.innerHTML = `<span class="queue-badge">Q${idx + 1}</span>
      <textarea class="queue-text" rows="1" placeholder="待发送内容"></textarea>
      <button class="queue-del" title="删除">✕</button>`;
    const ta = div.querySelector(".queue-text");
    ta.value = item.text;
    ta.addEventListener("input", () => {
      item.text = ta.value;
      autoResize(ta);
    });
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        ta.blur();
      }
    });
    // 双击编辑按钮聚焦
    div.addEventListener("dblclick", (e) => {
      if (e.target.classList.contains("queue-del")) return;
      ta.focus();
      ta.select();
    });
    div.querySelector(".queue-del").onclick = () => {
      sendQueue.splice(idx, 1);
      renderQueue();
    };
    box.appendChild(div);
  });
}

// 发送队列中的下一条（回复结束后自动调用）
async function processQueue() {
  if (state.streaming || !sendQueue.length) return;
  const item = sendQueue.shift();
  renderQueue();
  await doSend(item.text, item.attachFiles || null);
}

// 调用后端把历史消息压缩为摘要
async function compressMessages(messages) {
  const data = await api("/api/compress", {
    method: "POST",
    body: JSON.stringify({
      messages,
      provider_id: state.currentProviderId,
      model: state.currentModel,
    }),
  });
  return data.summary;
}

// 手动压缩当前会话（后端重写消息记录）
async function compressConversation() {
  if (!state.currentConvId) { alert("请先选择会话"); return; }
  if (!confirm("将当前会话历史压缩为摘要？压缩后旧消息会被替换。")) return;
  const btn = $("#compress-btn");
  if (btn) btn.disabled = true;
  try {
    const data = await api("/api/compress_conv", {
      method: "POST",
      body: JSON.stringify({
        conv_id: state.currentConvId,
        provider_id: state.currentProviderId,
        model: state.currentModel,
      }),
    });
    await loadMessages(state.currentConvId);
    alert("会话已压缩 ✓\n\n" + (data.summary || "").slice(0, 300) + ((data.summary || "").length > 300 ? "…" : ""));
  } catch (e) {
    alert("压缩失败：" + e.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ===== 思考模式（左侧问号徽标 / 顶栏开关联动） =====
function toggleThinking() {
  state.tbThinking = !state.tbThinking;
  syncThinkingUI();
}

function syncThinkingUI() {
  const active = state.tbThinking;
  const badge = $("#thinking-toggle");
  if (badge) badge.classList.toggle("active", active);
  $$(".tb-toggle[data-tb='thinking']").forEach((b) => b.classList.toggle("active", active));
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
  $("#agent-btn").onclick = () => {
    openModal("agent-modal");
    loadAgents("all");
  };
  $("#add-provider-btn").onclick = () => openProviderModal("");
  $("#send-btn").onclick = sendMessage;
  $("#attach-btn").onclick = openAttach;
  // 语音输入改用按住说话（pointerdown/pointerup），见 initSpeech()
  $("#file-input").onchange = (e) => { handleFiles(e.target.files); e.target.value = ""; };
  $("#mcp-transport").onchange = mcpFormVisible;
  // Agent 开关已移至设置面板（agent-switch-pref）

  const input = $("#chat-input");
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (state.streaming && e.ctrlKey) {
        // Ctrl+Enter：抢断发送
        const text = input.value.trim();
        if (!text && !pendingAttachments.length) return;
        // 插入队首并终止当前回复
        sendQueue.unshift({ id: ++queueSeq, text, attachFiles: pendingAttachments.length ? [...pendingAttachments] : null });
        if (pendingAttachments.length) { pendingAttachments = []; renderAttachPreview(); }
        renderQueue();
        input.value = "";
        autoResize();
        if (state.abortController) state.abortController.abort();
        return;
      }
      sendMessage();
    }
  });
  input.addEventListener("input", autoResize);

  // 聊天区滚动跟随：滚离底部时停止自动滚动并显示「下拉阅读」
  const chatArea = $("#chat-area");
  if (chatArea) {
    chatArea.addEventListener("scroll", onChatScroll, { passive: true });
    chatArea.addEventListener("wheel", onChatScroll, { passive: true });
    chatArea.addEventListener("touchmove", onChatScroll, { passive: true });
  }

  $("#provider-select").onchange = (e) => {
    state.currentProviderId = e.target.value;
    const p = getProvider(state.currentProviderId);
    state.currentModel = (p && p.models.length) ? p.models[0] : (p ? p.default_model : "");
    localStorage.setItem("abcode-provider", state.currentProviderId);
    localStorage.setItem("abcode-model", state.currentModel);
    updateModelSelect();
  };
  $("#model-select").onchange = (e) => { state.currentModel = e.target.value; localStorage.setItem("abcode-model", e.target.value); };

  // 模型类型切换（全部/本地/网络）
  $$(".model-type-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".model-type-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.modelTypeFilter = btn.dataset.type;
      updateProviderSelect();
      updateModelSelect();
    });
  });

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
        const freeModels = btn.dataset.free.split(",");
        const freeLabel = freeModels.length > 3 
          ? freeModels.slice(0, 3).join(", ") + ` 等${freeModels.length}个`
          : btn.dataset.free;
        info.innerHTML = `✨ <b>${btn.dataset.name}</b> 免费模型: <code>${freeLabel}</code><br>上下文长度: ${btn.dataset.ctx ? (parseInt(btn.dataset.ctx)/1000).toFixed(0) + "K" : "未设置"}`;
      } else {
        info.style.display = "none";
      }
      $("#pf-models").focus();
    };
  });

  // 知识库快捷引用（元素可能被移除，做空值保护避免中断后续绑定）
  const kbRefBtn = $("#kb-ref-btn");
  const kbRefClose = $("#kb-ref-close");
  const kbRefInput = $("#kb-ref-input");
  const kbRefPanel = $("#kb-ref-panel");
  if (kbRefBtn) kbRefBtn.onclick = openKbRef;
  if (kbRefClose) kbRefClose.onclick = closeKbRef;
  if (kbRefInput) {
    kbRefInput.addEventListener("input", (e) => {
      clearTimeout(kbRefTimer);
      kbRefTimer = setTimeout(() => searchKbRef(e.target.value), 300);
    });
  }
  // Ctrl+K 快捷键打开知识库引用
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "k") {
      e.preventDefault();
      if (kbRefPanel) openKbRef();
    }
    if (e.key === "Escape" && kbRefPanel && kbRefPanel.style.display !== "none") {
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
      else if (tb === "thinking") {
        state.tbThinking = btn.classList.contains("active");
        syncThinkingUI();
      }
    });
  });

  // 左侧思考模式问号徽标
  const thinkingToggle = $("#thinking-toggle");
  if (thinkingToggle) thinkingToggle.onclick = toggleThinking;
  syncThinkingUI();

  // 压缩会话按钮
  const compressBtn = $("#compress-btn");
  if (compressBtn) compressBtn.onclick = compressConversation;

  // 模型切换集中在右上角（provider-select / model-select），输入区不再放置

  // 主题切换（顶栏下拉）
  const themeSelect = $("#theme-select");
  if (themeSelect) {
    themeSelect.value = state.theme;
    themeSelect.addEventListener("change", () => applyTheme(themeSelect.value));
  }

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

  // 界面语言（持久化偏好）
  const langSel = document.getElementById("lang-select");
  if (langSel) {
    langSel.value = state.lang;
    langSel.addEventListener("change", () => {
      state.lang = langSel.value;
      localStorage.setItem("abcode-lang", state.lang);
      const info = $("#settings-lang-hint");
      if (info) {
        info.textContent = state.lang === "en" ? "English UI coming soon; preference saved." : "已保存语言偏好（完整英文界面待后续版本）";
        info.style.display = "block";
        setTimeout(() => { info.style.display = "none"; }, 2500);
      }
    });
  }

  // 时区（影响所有时间显示）
  const tzSel = document.getElementById("tz-select");
  if (tzSel) {
    tzSel.value = state.timezone || "Asia/Shanghai";
    tzSel.addEventListener("change", () => {
      state.timezone = tzSel.value;
      localStorage.setItem("abcode-timezone", state.timezone);
      const info = $("#settings-tz-hint");
      if (info) {
        info.textContent = "时区已更新，时间显示立即生效";
        info.style.display = "block";
        setTimeout(() => { info.style.display = "none"; }, 2500);
      }
      // 重绘当前可见的时间（刷新整个界面时间区域）
      if (state.currentConvId) loadMessages(state.currentConvId);
      if (currentWfView === "executions") loadWorkflowExecutions();
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

  // 粒子动画开关
  const particleAnimToggle = document.getElementById("particle-animate-toggle");
  if (particleAnimToggle) {
    particleAnimToggle.checked = state.particleAnimate;
    particleAnimToggle.addEventListener("change", () => {
      state.particleAnimate = particleAnimToggle.checked;
      saveParticleAnimationSettings();
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
  
  // 模式选择器
  initModeSelector();
  
  // 表情选择器
  initEmojiPicker();
  
  // 字符计数
  initCharCount();
  
  // 点击外部关闭弹出面板
  document.addEventListener("click", (e) => {
    var modePopup = document.getElementById("mode-popup");
    var closeModePopupEl = document.getElementById("close-mode-popup");
    var modeBtn = document.getElementById("mode-selector-btn");
    var closeModeBtn = document.getElementById("close-mode-btn");
    if (modePopup && modePopup.style.display !== "none" && !modePopup.contains(e.target) && (!modeBtn || !modeBtn.contains(e.target))) {
      modePopup.style.display = "none";
    }
    if (closeModePopupEl && closeModePopupEl.style.display !== "none" && !closeModePopupEl.contains(e.target) && (!closeModeBtn || !closeModeBtn.contains(e.target))) {
      closeModePopupEl.style.display = "none";
    }
  });
  
  // 工作流测试输入框事件
  const wfTestInput = $("#wf-test-input");
  if (wfTestInput) {
    wfTestInput.addEventListener("input", () => {
      updateSendBtnState();
      wfTestInput.style.height = "auto";
      wfTestInput.style.height = Math.min(wfTestInput.scrollHeight, 120) + "px";
    });
    wfTestInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        executeWfTestFromInput();
      }
    });
  }
}

function autoResize(el) {
  const input = el || $("#chat-input");
  if (!input) return;
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
}

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function escAttr(s) {
  return esc(s).replace(/'/g, "&#39;");
}

// ===== 表情选择器 =====
const EMOJI_SET = [
  "😀","😁","😂","🤣","😊","😇","🙂","😉",
  "😍","😘","😜","🤪","😎","🤩","🥳","😏",
  "😢","😭","😤","😡","🤯","😱","😴","🤗",
  "🤔","🫡","👍","👎","👏","🙏","💪","🤝",
  "👋","✌️","🤞","🖐️","❤️","🧡","💛","💚",
  "💙","💜","🖤","💯","✨","🔥","⭐","🎉",
  "🎊","🎯","🚀","✅","❌","⚠️","💡","📌",
  "📎","📚","💻","🧠","🤖","🐛","🔧","🛠️"
];

function initEmojiPicker() {
  const btn = $("#emoji-btn");
  const popup = $("#emoji-popup");
  const grid = $("#emoji-grid");
  if (!btn || !popup || !grid) return;

  // 渲染常用表情
  EMOJI_SET.forEach((e) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = e;
    b.title = e;
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      insertEmojiAtCursor(e);
      popup.style.display = "none";
      btn.classList.remove("active");
    });
    grid.appendChild(b);
  });

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const visible = popup.style.display !== "none";
    popup.style.display = visible ? "none" : "block";
    btn.classList.toggle("active", !visible);
  });

  // 点击外部关闭
  document.addEventListener("click", (e) => {
    if (popup.style.display !== "none" && !popup.contains(e.target) && e.target !== btn) {
      popup.style.display = "none";
      btn.classList.remove("active");
    }
  });
}

function insertEmojiAtCursor(emoji) {
  const input = $("#chat-input");
  if (!input) return;
  const start = input.selectionStart ?? input.value.length;
  const end = input.selectionEnd ?? input.value.length;
  input.value = input.value.slice(0, start) + emoji + input.value.slice(end);
  const pos = start + emoji.length;
  input.selectionStart = input.selectionEnd = pos;
  input.focus();
  autoResize(input);
  // 触发 input 事件，让字符计数等监听同步更新
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

// ===== 模式选择器 =====
let currentMode = "default";

function initModeSelector() {
  var btn = document.getElementById("mode-selector-btn");
  var popup = document.getElementById("mode-popup");
  var closeBtn = document.getElementById("close-mode-btn");
  var closePopup = document.getElementById("close-mode-popup");
  
  if (btn && popup) {
    btn.onclick = function(e) {
      e.stopPropagation();
      popup.style.display = popup.style.display === "none" ? "block" : "none";
      if (closePopup) closePopup.style.display = "none";
    };
  }
  if (closeBtn && closePopup) {
    closeBtn.onclick = function(e) {
      e.stopPropagation();
      closePopup.style.display = closePopup.style.display === "none" ? "block" : "none";
      if (popup) popup.style.display = "none";
    };
  }
}

// 启动时绑定模式选择器
document.addEventListener("DOMContentLoaded", function() {
  initModeSelector();
});

function selectMode(mode) {
  currentMode = mode;
  const modes = {
    default: { label: "默认" },
    goal: { label: "目标" },
    task: { label: "任务" }
  };
  
  const m = modes[mode];
  if (m) {
    $("#mode-label").textContent = m.label;
  }
  
  // 更新选中状态
  document.querySelectorAll(".mode-option-check").forEach(el => {
    el.classList.remove("active");
    el.textContent = "";
  });
  const check = $(`#mode-check-${mode}`);
  if (check) {
    check.classList.add("active");
    check.textContent = "✓";
  }
  
  closeModePopup();
}

function closeModePopup() {
  const popup = $("#mode-popup");
  if (popup) popup.style.display = "none";
}

// ===== 关闭模式 =====
let currentCloseMode = "off";
const closeModeConfig = {
  strict: { label: "严格模式", desc: "所有工具调用都需要审批，最高安全级别", icon: "⛔" },
  smart: { label: "智能模式", desc: "低风险工具自动放行，中高风险工具需要审批", icon: "⚠️" },
  auto: { label: "自动模式", desc: "仅被明确标记为需要审批的工具才会要求审批", icon: "🔵" },
  off: { label: "关闭模式", desc: "关闭所有工具审批，所有工具自动执行", icon: "✅" }
};

function toggleCloseMode() {
  const popup = $("#close-mode-popup");
  if (!popup) return;
  const isVisible = popup.style.display !== "none";
  if (isVisible) {
    closeCloseModePopup();
  } else {
    popup.style.display = "block";
    updateCloseModeChecks();
  }
}

function closeCloseModePopup() {
  const popup = $("#close-mode-popup");
  if (popup) popup.style.display = "none";
}

function selectCloseMode(mode) {
  currentCloseMode = mode;
  const config = closeModeConfig[mode];
  // 更新按钮显示
  const btn = $("#close-mode-btn");
  if (btn) {
    const labelSpan = btn.querySelector("span");
    if (labelSpan) labelSpan.textContent = config.label;
    if (mode === "off") {
      btn.style.borderColor = "#22c55e";
      btn.style.color = "#22c55e";
      btn.querySelector("svg:first-child").style.color = "#22c55e";
    } else if (mode === "strict") {
      btn.style.borderColor = "#ef4444";
      btn.style.color = "#ef4444";
      btn.querySelector("svg:first-child").style.color = "#ef4444";
    } else if (mode === "smart") {
      btn.style.borderColor = "#f59e0b";
      btn.style.color = "#f59e0b";
      btn.querySelector("svg:first-child").style.color = "#f59e0b";
    } else {
      btn.style.borderColor = "#6366f1";
      btn.style.color = "#6366f1";
      btn.querySelector("svg:first-child").style.color = "#6366f1";
    }
  }
  // 更新标题
  const titleEl = $("#close-mode-title");
  const descEl = $("#close-mode-desc");
  if (titleEl) titleEl.textContent = config.label;
  if (descEl) descEl.textContent = config.desc;
  updateCloseModeChecks();
  closeCloseModePopup();
}

function updateCloseModeChecks() {
  ["strict", "smart", "auto", "off"].forEach(mode => {
    const check = $(`#close-mode-check-${mode}`);
    if (check) check.textContent = mode === currentCloseMode ? "✓" : "";
    const option = $(`.close-mode-option[data-close-mode="${mode}"]`);
    if (option) {
      if (mode === currentCloseMode) option.classList.add("active");
      else option.classList.remove("active");
    }
  });
}

// ===== 字符计数 =====
function initCharCount() {
  const input = $("#chat-input");
  const counter = $("#char-count");
  
  if (input && counter) {
    input.addEventListener("input", () => {
      const len = input.value.length;
      counter.textContent = `${len}/10000`;
      if (len > 10000) {
        counter.style.color = "#ef4444";
      } else if (len > 8000) {
        counter.style.color = "#f59e0b";
      } else {
        counter.style.color = "";
      }
    });
  }
}

// ===== 侧边栏：折叠 / 展开（推入 / 推出） + 导航拖拽排序 =====
function initSidebar() {
  const sidebar = $("#sidebar");
  const toggle = $("#sidebar-toggle");
  if (!sidebar || !toggle) return;

  // 恢复折叠状态
  if (localStorage.getItem("abcode-sidebar-collapsed") === "1") {
    sidebar.classList.add("collapsed");
    $("#main").classList.add("sidebar-collapsed");
  }

  toggle.addEventListener("click", () => {
    sidebar.classList.toggle("collapsed");
    const isCollapsed = sidebar.classList.contains("collapsed");
    localStorage.setItem("abcode-sidebar-collapsed", isCollapsed ? "1" : "0");
    $("#main").classList.toggle("sidebar-collapsed", isCollapsed);
    toggle.textContent = isCollapsed ? "»" : "«";
    // 折叠后内新栏按钮挤压，触发窗口自适应
    window.dispatchEvent(new Event("resize"));
  });
  toggle.textContent = sidebar.classList.contains("collapsed") ? "»" : "«";

  // 社交栏导航：拖拽排序（HTML5 draggable）
  const footer = document.querySelector(".sidebar-footer");
  if (!footer) return;
  const navIds = ["agent-btn", "team-btn", "workflow-btn",
    "tools-btn", "kb-btn", "cron-btn", "channel-btn", "settings-btn"];
  const STORE = "abcode-nav-order";
  // 恢复已保存顺序
  const saved = localStorage.getItem(STORE);
  const savedIds = saved ? JSON.parse(saved) : [];
  if (savedIds.length) {
    savedIds.forEach((id) => {
      const btn = document.getElementById(id);
      if (btn) footer.appendChild(btn);
    });
  }
  footer.addEventListener("dragstart", (e) => {
    const btn = e.target.closest(".btn-sidebar");
    if (!btn) return;
    e.dataTransfer.setData("text/plain", btn.id);
    e.dataTransfer.effectAllowed = "move";
    btn.classList.add("dragging");
  });
  footer.addEventListener("dragend", (e) => {
    const btn = e.target.closest(".btn-sidebar");
    if (btn) btn.classList.remove("dragging");
    footer.querySelectorAll(".drop-hint").forEach((el) => el.remove());
    const order = Array.from(footer.querySelectorAll(".btn-sidebar")).map((b) => b.id);
    localStorage.setItem(STORE, JSON.stringify(order));
  });
  footer.addEventListener("dragover", (e) => {
    e.preventDefault();
    const target = e.target.closest(".btn-sidebar");
    if (!target) return;
    target.classList.add("drop-hint");
  });
  footer.addEventListener("dragleave", (e) => {
    const target = e.target.closest(".btn-sidebar");
    if (target) target.classList.remove("drop-hint");
  });
  footer.addEventListener("drop", (e) => {
    e.preventDefault();
    const target = e.target.closest(".btn-sidebar");
    if (!target) return;
    target.classList.remove("drop-hint");
    const dragId = e.dataTransfer.getData("text/plain");
    const dragBtn = document.getElementById(dragId);
    if (!dragBtn || dragBtn === target) return;
    const box = target.getBoundingClientRect();
    const before = e.clientY < box.top + box.height / 2;
    footer.insertBefore(dragBtn, before ? target : target.nextSibling);
    const order = Array.from(footer.querySelectorAll(".btn-sidebar")).map((b) => b.id);
    localStorage.setItem(STORE, JSON.stringify(order));
  });
}
init();
initSidebar();
