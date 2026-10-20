const $ = (sel) => document.querySelector(sel);

const messagesEl = $('#messages');
const inputEl = $('#input');
const sendBtn = $('#sendBtn');
const stopBtn = $('#stopBtn');
const refreshBtn = $('#refreshBtn');
const viewToggleBtn = $('#viewToggleBtn');
const sidebarToggleBtn = $('#sidebarToggleBtn');
const newSessionBtn = $('#newSessionBtn');
const profileSelect = $('#profileSelect');
const sessionList = $('#sessionList');
const sessionTitle = $('#sessionTitle');
const layoutEl = document.querySelector('.layout');
const shotEl = $('#shot');
const placeholderEl = $('#placeholder');
const statusTextEl = $('#statusText');
const statusDotEl = $('#status .dot');

let es = null;
let currentMessageId = null;

let sessions = []; // 会话摘要 [{id, name, updatedAt, messageCount}]
let currentSessionId = null;
let currentSession = null; // 当前会话完整对象
let profiles = [];
let sidebarVisible = true;
let viewVisible = false;

// ── DOM helpers ──────────────────────────────────────────────────────────

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function scrollBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setStatus(text, kind) {
  statusTextEl.textContent = text;
  statusDotEl.className = 'dot' + (kind ? ' ' + kind : '');
}

async function refreshStatus() {
  try {
    const r = await fetch('/api/status');
    const j = await r.json();
    setStatus(j.connected ? '已连接 Blender' : '未连接 Blender', j.connected ? 'ok' : 'err');
  } catch {
    setStatus('服务不可用', 'err');
  }
}

function autoResize() {
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 200) + 'px';
}

function formatTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  return d.toDateString() === now.toDateString()
    ? d.toTimeString().slice(0, 5)
    : `${d.getMonth() + 1}/${d.getDate()}`;
}

// ── 会话列表 ────────────────────────────────────────────────────────────

function renderSessionList() {
  sessionList.innerHTML = '';
  if (sessions.length === 0) {
    sessionList.appendChild(el('div', 'session-empty', '暂无会话'));
    return;
  }
  for (const s of sessions) {
    const item = el('div', 'session-item' + (s.id === currentSessionId ? ' active' : ''));
    item.appendChild(el('span', 'name', s.name));
    item.appendChild(el('span', 'time', formatTime(s.updatedAt)));
    const del = el('button', 'delete', '×');
    del.title = '删除会话';
    del.addEventListener('click', (e) => {
      e.stopPropagation();
      void deleteSession(s.id);
    });
    item.appendChild(del);
    item.addEventListener('click', () => void selectSession(s.id));
    sessionList.appendChild(item);
  }
}

async function loadSessions() {
  try {
    const r = await fetch('/api/sessions');
    const j = await r.json();
    sessions = j.sessions ?? [];
    renderSessionList();
  } catch {
    // ignore
  }
}

async function createSession() {
  closeStream();
  const settingsProfile = currentSession?.settingsProfile ?? '';
  try {
    const r = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settingsProfile }),
    });
    const j = await r.json();
    if (!r.ok) {
      alert('新建会话失败：' + (j.error?.message || r.status));
      return;
    }
    await loadSessions();
    await selectSession(j.session.id);
  } catch (e) {
    alert('新建会话失败：' + e.message);
  }
}

async function selectSession(id) {
  closeStream();
  currentSessionId = id;
  currentSession = null;
  localStorage.setItem('blenderharness:lastSessionId', id);
  sessionTitle.textContent = '加载中…';
  messagesEl.innerHTML = '';
  shotEl.hidden = true;
  placeholderEl.hidden = false;
  placeholderEl.textContent = '启动后，建模过程会自动渲染显示在这里';
  renderSessionList();
  syncProfileSelect();
  try {
    const [sr, mr] = await Promise.all([
      fetch(`/api/sessions/${id}`),
      fetch(`/api/sessions/${id}/messages`),
    ]);
    const sj = await sr.json();
    const mj = await mr.json();
    if (sr.ok) {
      currentSession = sj.session;
      sessionTitle.textContent = sj.session.name;
      syncProfileSelect();
    }
    messagesEl.innerHTML = '';
    for (const m of mj.messages ?? []) renderHistoryEntry(m);
    scrollBottom();
  } catch {
    // ignore
  }
  refreshStatus();
}

async function deleteSession(id) {
  if (!confirm('删除该会话及其对话记录？')) return;
  try {
    const r = await fetch(`/api/sessions/${id}`, { method: 'DELETE' });
    if (!r.ok) {
      const j = await r.json();
      alert('删除失败：' + (j.error?.message || r.status));
      return;
    }
    await loadSessions();
    if (currentSessionId === id) {
      const target = sessions[0];
      if (target) await selectSession(target.id);
      else await createSession();
    }
  } catch (e) {
    alert('删除失败：' + e.message);
  }
}

function toggleSidebar() {
  sidebarVisible = !sidebarVisible;
  layoutEl.classList.toggle('sidebar-hidden', !sidebarVisible);
}

// ── 模型 profile ────────────────────────────────────────────────────────

function syncProfileSelect() {
  profileSelect.value = currentSession?.settingsProfile ?? '';
  profileSelect.disabled = !currentSessionId;
}

async function loadProfiles() {
  try {
    const r = await fetch('/api/settings-profiles');
    const j = await r.json();
    profiles = j.profiles ?? [];
    profileSelect.innerHTML = '';
    for (const p of profiles) {
      const opt = el('option', null, p.name === '' ? `${p.label}（默认）` : p.label);
      opt.value = p.name;
      profileSelect.appendChild(opt);
    }
    syncProfileSelect();
  } catch {
    // ignore
  }
}

// ── 消息渲染 ────────────────────────────────────────────────────────────

function addUserMessage(text) {
  const row = el('div', 'msg user');
  const bubble = el('div', 'bubble');
  bubble.appendChild(el('div', 'content', text));
  row.appendChild(bubble);
  messagesEl.appendChild(row);
  scrollBottom();
}

function addAssistantMessage() {
  const row = el('div', 'msg assistant');
  const bubble = el('div', 'bubble');
  row.appendChild(bubble);
  messagesEl.appendChild(row);
  scrollBottom();
  return { bubble, textEl: null, thinkingEl: null, textBuf: '', toolEls: new Map() };
}

function ensureTextEl(state) {
  if (!state.textEl) {
    state.textEl = el('div', 'content');
    state.bubble.appendChild(state.textEl);
  }
  return state.textEl;
}

function ensureThinkingEl(state) {
  if (!state.thinkingEl) {
    const details = el('details', 'thinking');
    details.appendChild(el('summary', null, '思考过程'));
    state.thinkingEl = el('pre', 'thinking-body');
    details.appendChild(state.thinkingEl);
    state.bubble.appendChild(details);
  }
  return state.thinkingEl;
}

function appendDelta(state, delta) {
  state.textBuf += delta;
  ensureTextEl(state).textContent = state.textBuf;
  scrollBottom();
}

function appendThinking(state, delta) {
  ensureThinkingEl(state).textContent += delta;
}

function addTool(state, { toolUseId, toolName, input }) {
  const card = el('div', 'tool-card');
  const head = el('div', 'tool-head');
  const statusEl = el('span', 'tool-status running', '运行中');
  head.appendChild(el('span', 'tool-name', toolName));
  head.appendChild(statusEl);
  const body = el('div', 'tool-body');
  body.appendChild(el('pre', 'tool-input', JSON.stringify(input ?? {}, null, 2)));
  card.appendChild(head);
  card.appendChild(body);
  state.bubble.appendChild(card);
  state.toolEls.set(toolUseId, { statusEl, body });
  scrollBottom();
}

function updateToolResult(state, { toolUseId, isError, content }) {
  const t = state.toolEls.get(toolUseId);
  if (!t) return;
  t.statusEl.className = 'tool-status ' + (isError ? 'error' : 'done');
  t.statusEl.textContent = isError ? '失败' : '完成';
  if (content) t.body.appendChild(el('pre', 'tool-output', content));
  scrollBottom();
}

function showScreenshot(png) {
  shotEl.src = 'data:image/png;base64,' + png;
  shotEl.hidden = false;
  placeholderEl.hidden = true;
}

// ── 历史恢复 ────────────────────────────────────────────────────────────

function renderHistoryEntry(m) {
  if (m.role === 'user') {
    addUserMessage(m.text);
    return;
  }
  const state = addAssistantMessage();
  if (m.text) {
    state.textBuf = m.text;
    ensureTextEl(state).textContent = m.text;
  }
  if (m.thinking) ensureThinkingEl(state).textContent = m.thinking;
  for (const t of m.tools ?? []) {
    const card = el('div', 'tool-card');
    const head = el('div', 'tool-head');
    head.appendChild(el('span', 'tool-name', t.name));
    head.appendChild(
      el('span', 'tool-status ' + (t.isError ? 'error' : 'done'), t.isError ? '失败' : '完成'),
    );
    const body = el('div', 'tool-body');
    body.appendChild(el('pre', 'tool-input', JSON.stringify(t.input ?? {}, null, 2)));
    if (t.content) body.appendChild(el('pre', 'tool-output', t.content));
    card.appendChild(head);
    card.appendChild(body);
    state.bubble.appendChild(card);
  }
  if (m.meta?.costUsd != null) {
    state.bubble.appendChild(
      el(
        'div',
        'meta',
        `耗时 ${(m.meta.durationMs / 1000).toFixed(1)}s · $${m.meta.costUsd.toFixed(4)} · ${m.meta.numTurns} 轮`,
      ),
    );
  }
  scrollBottom();
}

// ── 流处理 ──────────────────────────────────────────────────────────────

function setBusy(busy) {
  sendBtn.disabled = busy;
  inputEl.disabled = busy;
  stopBtn.hidden = !busy;
  if (busy) setStatus('建模中…', 'busy');
  else refreshStatus();
}

function closeStream() {
  if (es) {
    es.close();
    es = null;
  }
  currentMessageId = null;
  setBusy(false);
}

function openStream(streamUrl, state) {
  es = new EventSource(streamUrl);

  es.addEventListener('message.delta', (e) => appendDelta(state, JSON.parse(e.data).delta));
  es.addEventListener('message.thinking', (e) => appendThinking(state, JSON.parse(e.data).delta));
  es.addEventListener('tool.use', (e) => addTool(state, JSON.parse(e.data)));
  es.addEventListener('tool.result', (e) => updateToolResult(state, JSON.parse(e.data)));
  es.addEventListener('screenshot', (e) => showScreenshot(JSON.parse(e.data).png));

  es.addEventListener('message.done', (e) => {
    const d = JSON.parse(e.data);
    if (d.stats?.costUsd != null) {
      const meta = el(
        'div',
        'meta',
        `耗时 ${(d.stats.durationMs / 1000).toFixed(1)}s · $${d.stats.costUsd.toFixed(4)} · ${d.stats.numTurns} 轮`,
      );
      state.bubble.appendChild(meta);
    } else if (d.stopped) {
      state.bubble.appendChild(el('div', 'meta', '已停止'));
    }
    closeStream();
    void loadSessions();
  });

  es.addEventListener('message.error', (e) => {
    state.bubble.appendChild(el('div', 'error-box', '错误：' + JSON.parse(e.data).error));
    closeStream();
    void loadSessions();
  });

  es.addEventListener('stream.closed', () => closeStream());
}

async function send() {
  const text = inputEl.value.trim();
  if (!text || sendBtn.disabled) return;
  if (!currentSessionId) return;

  addUserMessage(text);
  inputEl.value = '';
  autoResize();
  setBusy(true);
  const state = addAssistantMessage();

  try {
    const r = await fetch(`/api/sessions/${currentSessionId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const j = await r.json();
    if (!r.ok) {
      if (r.status === 409) {
        state.bubble.appendChild(el('div', 'error-box', '已有运行中的对话，请先停止。'));
      } else {
        state.bubble.appendChild(el('div', 'error-box', '错误：' + (j.error?.message || r.status)));
      }
      setBusy(false);
      return;
    }
    if (j.sessionName) {
      sessionTitle.textContent = j.sessionName;
      const s = sessions.find((x) => x.id === currentSessionId);
      if (s) s.name = j.sessionName;
      renderSessionList();
    }
    currentMessageId = j.messageId;
    openStream(j.streamUrl, state);
  } catch (err) {
    state.bubble.appendChild(el('div', 'error-box', '请求失败：' + err.message));
    setBusy(false);
  }
}

async function stop() {
  if (!currentMessageId) return;
  try {
    await fetch(`/api/messages/${currentMessageId}/stop`, { method: 'POST' });
  } catch {
    // ignore
  }
}

async function refreshScreenshot() {
  placeholderEl.textContent = '渲染中…';
  placeholderEl.hidden = false;
  shotEl.hidden = true;
  try {
    const r = await fetch('/api/screenshot');
    const j = await r.json();
    if (j.png) {
      showScreenshot(j.png);
    } else {
      placeholderEl.textContent = '当前无活动场景，或渲染失败';
      placeholderEl.hidden = false;
    }
  } catch (err) {
    placeholderEl.textContent = '渲染失败：' + err.message;
    placeholderEl.hidden = false;
  }
}

// ── 实时视图折叠 ────────────────────────────────────────────────────────

function setViewVisible(visible) {
  viewVisible = visible;
  layoutEl.classList.toggle('view-hidden', !visible);
  viewToggleBtn.textContent = visible ? '隐藏视图' : '视图';
  viewToggleBtn.classList.toggle('active', visible);
  if (visible) refreshScreenshot();
}

// ── 事件绑定 ────────────────────────────────────────────────────────────

sendBtn.addEventListener('click', (e) => {
  e.preventDefault();
  void send();
});
inputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    void send();
  }
});
inputEl.addEventListener('input', autoResize);
stopBtn.addEventListener('click', () => void stop());
refreshBtn.addEventListener('click', () => void refreshScreenshot());
viewToggleBtn.addEventListener('click', () => setViewVisible(!viewVisible));
sidebarToggleBtn.addEventListener('click', toggleSidebar);
newSessionBtn.addEventListener('click', () => void createSession());

profileSelect.addEventListener('change', async () => {
  if (!currentSessionId) return;
  const name = profileSelect.value;
  try {
    const r = await fetch(`/api/sessions/${currentSessionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settingsProfile: name }),
    });
    if (!r.ok) {
      const j = await r.json();
      alert('切换模型失败：' + (j.error?.message || r.status));
      syncProfileSelect();
      return;
    }
    const j = await r.json();
    currentSession = j.session;
  } catch (e) {
    alert('切换模型失败：' + e.message);
  }
});

// ── 初始化 ──────────────────────────────────────────────────────────────

async function init() {
  await loadProfiles();
  await loadSessions();
  const lastId = localStorage.getItem('blenderharness:lastSessionId');
  const target = sessions.find((s) => s.id === lastId) ?? sessions[0];
  if (target) await selectSession(target.id);
  else await createSession();
  refreshStatus();
}

void init();
