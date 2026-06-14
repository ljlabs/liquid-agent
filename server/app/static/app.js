// ---------- helpers ----------
function getEndpoint() {
  return document.getElementById('endpoint-input').value;
}

async function dbFetch(path, opts = {}) {
  const endpoint = getEndpoint();
  const res = await fetch(`${endpoint}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ---------- collapsible sidebar sections ----------
document.querySelectorAll('[data-toggle]').forEach(el => {
  el.addEventListener('click', () => el.parentElement.classList.toggle('collapsed'));
});

// ---------- tool block collapse ----------
document.querySelectorAll('[data-toggle-tool]').forEach(header => {
  header.addEventListener('click', () => {
    const body = header.nextElementSibling;
    const chev = header.querySelector('.chev');
    body.classList.toggle('hidden');
    chev.classList.toggle('open');
  });
});

// ---------- thinking block collapse ----------
document.querySelectorAll('[data-toggle-think]').forEach(block => {
  block.addEventListener('click', () => block.classList.toggle('collapsed'));
});

// ---------- session list from DB ----------
async function loadSessionList() {
  try {
    const data = await dbFetch('/v1/db/sessions');
    const list = document.getElementById('session-list');
    list.innerHTML = '';
    for (const s of data.sessions) {
      const item = document.createElement('div');
      item.className = 'session-item';
      item.dataset.session = s.id;
      const ago = formatTimeAgo(s.updated_at);
      item.innerHTML = `<span class="dot"></span><span class="title">${escapeHtml(s.title)}</span><span class="meta">${ago}</span>`;
      item.addEventListener('click', () => switchToSession(s.id, s.title, item));
      list.appendChild(item);
    }
  } catch (e) {
    console.error('Failed to load sessions:', e);
  }
}

function formatTimeAgo(ts) {
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return 'now';
  if (diff < 3600) return Math.floor(diff / 60) + 'm';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h';
  return Math.floor(diff / 86400) + 'd';
}

async function switchToSession(sessionId, title, clickedItem) {
  activeSessionId = sessionId;
  document.querySelectorAll('.session-item').forEach(i => i.classList.remove('active'));
  if (clickedItem) clickedItem.classList.add('active');
  document.getElementById('session-id-tag').textContent = sessionId;
  document.getElementById('session-title').textContent = title || 'Session';
  document.getElementById('conversation').innerHTML = '';

  try {
    const data = await dbFetch(`/v1/db/sessions/${sessionId}/messages`);
    for (const msg of data.messages) {
      if (msg.role === 'user') {
        appendUserMessage(msg.content);
      } else if (msg.role === 'assistant' && msg.type === 'text') {
        appendAssistantMessage(msg.content);
      } else if (msg.role === 'assistant' && msg.type === 'thinking') {
        // Could render thinking blocks — skip for now, it's historical
      } else if (msg.type === 'tool_use') {
        // Could render tool blocks — skip for now
      }
    }
  } catch (e) {
    console.error('Failed to load messages:', e);
  }
}

// ---------- new session ----------
document.getElementById('new-session').addEventListener('click', async () => {
  try {
    // Call API to create session eagerly in SDK and DB
    const data = await dbFetch('/v1/sessions', {
      method: 'POST',
      body: JSON.stringify({
        cwd: document.getElementById('cwd-input')?.value || '',
        model: document.getElementById('model-select')?.value || 'claude-sonnet-4-6',
      }),
    });

    const sessionId = data.session_id;

    // Update UI state
    activeSessionId = sessionId;
    document.getElementById('session-id-tag').textContent = sessionId;
    document.getElementById('turn-tag').textContent = 'Turn 0';
    document.getElementById('conversation').innerHTML = '';
    document.getElementById('prompt-input').focus();

    // Refresh the sidebar list to show the newly created session
    await loadSessionList();

    // Mark the new session as active in the list
    document.querySelectorAll('.session-item').forEach(item => {
      if (item.dataset.session === sessionId) {
        item.classList.add('active');
      } else {
        item.classList.remove('active');
      }
    });

  } catch (e) {
    console.error('Failed to create new session:', e);
    alert('Failed to create session. Please check server connection.');
  }
});

// ---------- right panel tabs ----------
document.querySelectorAll('.rp-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.rp-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.rp-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    document.querySelector(`[data-rp-content="${tab.dataset.rpTab}"]`).classList.add('active');
  });
});

// ---------- mode pill cycle ----------
const modes = [
  { cls: 'active-plan', label: 'Plan mode', icon: '<path d="M3 3h10v10H3z"/><path d="M3 6.5h10M6.5 3v10"/>', state: 'plan' },
  { cls: 'active-accept', label: 'Auto-accept edits', icon: '<path d="M3 8l3 3 7-7"/>', state: 'accept' },
  { cls: '', label: 'Default mode', icon: '<circle cx="8" cy="8" r="5"/>', state: 'default' }
];
let modeIdx = 0;
const modePill = document.getElementById('mode-pill');
const modeState = { current: 'default' };

modePill.addEventListener('click', () => {
  modeIdx = (modeIdx + 1) % modes.length;
  const m = modes[modeIdx];
  modeState.current = m.state;
  modePill.className = 'mode-pill ' + m.cls;
  modePill.querySelector('svg').innerHTML = m.icon;
  modePill.childNodes[modePill.childNodes.length - 1].textContent = ' ' + m.label;
});

// ---------- textarea autosize + char count ----------
const input = document.getElementById('prompt-input');
const charCount = document.getElementById('char-count');
input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 160) + 'px';
  charCount.textContent = input.value.length;

  const menu = document.getElementById('slash-menu');
  if (input.value.startsWith('/')) menu.classList.add('open');
  else menu.classList.remove('open');
});

// slash menu selection
document.querySelectorAll('.slash-item').forEach(item => {
  item.addEventListener('click', () => {
    input.value = item.querySelector('.cmd').textContent + ' ';
    document.getElementById('slash-menu').classList.remove('open');
    input.focus();
  });
});

// ---------- send / stop button + planning & approval workflow ----------
const sendBtn = document.getElementById('send-btn');
const conversation = document.getElementById('conversation');
const streamStatus = document.getElementById('stream-status');
let streaming = false;
let activeSessionId = null;
let awaitingApproval = false;
let currentStreamAbortController = null;

function scrollToBottom() {
  conversation.scrollTop = conversation.scrollHeight;
}

function appendUserMessage(text) {
  const div = document.createElement('div');
  div.className = 'msg user';
  div.innerHTML = `<div class="avatar">U</div><div class="msg-body">
    <div class="msg-meta"><span class="role">You</span><span>${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</span></div>
    <div class="msg-content"></div></div>`;
  div.querySelector('.msg-content').textContent = text;
  conversation.appendChild(div);
  scrollToBottom();
}

function appendAssistantStub() {
  const div = document.createElement('div');
  div.className = 'msg assistant';
  div.innerHTML = `<div class="avatar">A</div><div class="msg-body">
    <div class="msg-meta"><span class="role">Claude</span><span>${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</span></div>
    <div class="msg-content"><span class="cursor-blink"></span></div></div>`;
  conversation.appendChild(div);
  scrollToBottom();
  return div;
}

function appendAssistantMessage(text) {
  const div = document.createElement('div');
  div.className = 'msg assistant';
  div.innerHTML = `<div class="avatar">A</div><div class="msg-body">
    <div class="msg-meta"><span class="role">Claude</span><span></span></div>
    <div class="msg-content"></div></div>`;
  div.querySelector('.msg-content').textContent = text;
  conversation.appendChild(div);
  scrollToBottom();
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function setStreaming(on) {
  streaming = on;
  if (on) {
    sendBtn.classList.add('stop');
    sendBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor"><rect x="3" y="3" width="10" height="10" rx="1"/></svg>';
    streamStatus.textContent = 'streaming…';
  } else {
    sendBtn.classList.remove('stop');
    sendBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M2 2l12 6-12 6 3-6-3-6z"/></svg>';
    streamStatus.textContent = 'idle';
  }
}

function setAwaitingApproval(on) {
  awaitingApproval = on;
  if (on) {
    input.disabled = true;
    sendBtn.disabled = true;
    streamStatus.textContent = 'awaiting approval…';
  } else {
    input.disabled = false;
    sendBtn.disabled = false;
    streamStatus.textContent = 'idle';
  }
}

async function handleSend() {
  if (streaming) {
    if (currentStreamAbortController) {
      currentStreamAbortController.abort();
    }
    setStreaming(false);
    streamStatus.textContent = 'interrupted';
    return;
  }
  const text = input.value.trim();
  if (!text) return;

  appendUserMessage(text);
  input.value = '';
  input.style.height = 'auto';
  charCount.textContent = '0';

  const endpoint = document.getElementById('endpoint-input').value;
  const model = document.getElementById('model-select').value;
  const mode = modeState.current;

  await sendToWrapper(endpoint, model, text, { planning: mode === 'plan' });
}

async function sendToWrapper(endpoint, model, userMessage, options = {}) {
  currentStreamAbortController = new AbortController();
  const msgEl = appendAssistantStub();
  const contentEl = msgEl.querySelector('.msg-content');
  setStreaming(true);

  try {
    const response = await fetch(`${endpoint}/v1/sessions/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: userMessage,
        session_id: activeSessionId,
        model,
        planning_mode: options.planning || false,
        auto_approve: modeState.current === 'accept'
      }),
      signal: currentStreamAbortController.signal
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;

        try {
          const event = JSON.parse(line.slice(6));
          handleStreamEvent(event, msgEl);
        } catch (e) {
          console.error('Failed to parse event:', e);
        }
      }
    }

    setStreaming(false);
  } catch (err) {
    if (err.name !== 'AbortError') {
      contentEl.innerHTML += `<div style="color:var(--err); margin-top:4px;">Error: ${escapeHtml(err.message)}</div>`;
    }
    setStreaming(false);
  }
}

function handleStreamEvent(event, msgEl) {
  const contentEl = msgEl.querySelector('.msg-content');
  const bodyEl = msgEl.querySelector('.msg-body');

  switch (event.type) {
    case 'session':
      activeSessionId = event.session_id;
      document.getElementById('session-id-tag').textContent = event.session_id;
      if (event.title) {
        document.getElementById('session-title').textContent = event.title;
      }
      if (event.cwd) {
        document.getElementById('cwd-input').value = event.cwd;
        document.getElementById('cwd-display').textContent = event.cwd;
      }
      // Refresh sidebar to show new session
      loadSessionList();
      break;

    case 'text':
      if (!contentEl.innerHTML.includes('cursor-blink')) {
        contentEl.textContent += event.data;
      } else {
        const cursor = contentEl.querySelector('.cursor-blink');
        cursor.before(document.createTextNode(event.data));
      }
      scrollToBottom();
      break;

    case 'thinking':
      appendOrUpdateThinking(msgEl, event);
      scrollToBottom();
      break;

    case 'tool_use':
      appendToolBlock(bodyEl, {
        id: event.tool_id || Math.random().toString(36),
        name: event.name,
        target: (event.input && (event.input.path || event.input.command))
          || (event.input && Object.keys(event.input).length ? JSON.stringify(event.input).slice(0, 60) : ''),
        status: 'running',
        input: event.input || {}
      });
      scrollToBottom();
      break;

    case 'tool_result':
      const toolBlock = bodyEl.querySelector(`[data-tool-id="${event.tool_id}"]`);
      if (toolBlock) {
        updateToolBlock(toolBlock, {
          status: 'success',
          output: event.output
        });
      }
      scrollToBottom();
      break;

    case 'tool_error':
      const errBlock = bodyEl.querySelector(`[data-tool-id="${event.tool_id}"]`);
      if (errBlock) {
        updateToolBlock(errBlock, {
          status: 'error',
          output: event.error
        });
      }
      scrollToBottom();
      break;

    case 'permission_request':
      setAwaitingApproval(true);
      appendPermissionCard(bodyEl, event);
      scrollToBottom();
      break;

    case 'planning_complete':
      if (modeState.current === 'plan') {
        setAwaitingApproval(true);
        appendPlanningApprovalCard(bodyEl, event.plan || contentEl.textContent);
      }
      scrollToBottom();
      break;

    case 'system':
      addLogLine('info', event.subtype || 'system');
      break;

    case 'result':
      finalizeAssistantMessage(msgEl, event);
      scrollToBottom();
      break;

    case 'error':
      contentEl.innerHTML += `<div style="color:var(--err); margin-top:4px;">Error: ${escapeHtml(event.message)}</div>`;
      scrollToBottom();
      break;

    case 'done':
      const cursor = contentEl.querySelector('.cursor-blink');
      if (cursor) cursor.remove();
      break;
  }
}

function appendOrUpdateThinking(msgEl, event) {
  const bodyEl = msgEl.querySelector('.msg-body');
  let block = bodyEl.querySelector('.thinking-block.streaming');
  if (!block) {
    block = document.createElement('div');
    block.className = 'thinking-block streaming';
    block.innerHTML = `
      <div class="tlabel">
        <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="8" cy="8" r="6"/><path d="M8 5v3l2 2"/></svg>
        Thinking
      </div>
      <div class="tbody"></div>`;
    block.addEventListener('click', () => block.classList.toggle('collapsed'));
    const contentEl = msgEl.querySelector('.msg-content');
    contentEl.before(block);
  }
  if (event.data) {
    block.querySelector('.tbody').textContent += event.data;
  }
  if (event.done) {
    block.classList.remove('streaming');
    block.classList.add('collapsed');
  }
}

function finalizeAssistantMessage(msgEl, result) {
  const cursor = msgEl.querySelector('.cursor-blink');
  if (cursor) cursor.remove();

  if (result.is_error) {
    streamStatus.textContent = `error: ${result.stop_reason || 'unknown'}`;
  }

  const usage = result.usage || {};
  const inputTok = usage.input_tokens ?? '–';
  const outputTok = usage.output_tokens ?? '–';
  const cost = result.cost_usd != null ? `$${Number(result.cost_usd).toFixed(4)}` : '–';
  const duration = result.duration_ms != null ? `${(result.duration_ms / 1000).toFixed(1)}s` : '–';

  const stats = document.createElement('div');
  stats.className = 'msg-stats';
  stats.innerHTML = `
    <span class="stat">⏱ ${duration}</span>
    <span class="stat">↑ ${inputTok} tok</span>
    <span class="stat">↓ ${outputTok} tok</span>
    <span class="stat">${cost}</span>
  `;
  msgEl.querySelector('.msg-body').appendChild(stats);

  if (result.num_turns != null) {
    document.getElementById('turn-tag').textContent = `Turn ${result.num_turns}`;
  }
}

function addLogLine(level, text) {
  const logsTab = document.querySelector('[data-rp-content="logs"]');
  if (!logsTab) return;
  const line = document.createElement('div');
  line.className = `log-line ${level}`;
  line.innerHTML = `<span class="lvl">${level === 'error' ? '✕' : level === 'warn' ? '!' : 'i'}</span><span class="ts">${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'})}</span><span>${escapeHtml(text)}</span>`;
  logsTab.appendChild(line);
  logsTab.scrollTop = logsTab.scrollHeight;
}

function appendPermissionCard(bodyEl, event) {
  if (bodyEl.querySelector('.permission-card')) return;

  const card = document.createElement('div');
  card.className = 'permission-card';
  card.innerHTML = `
    <div class="ptitle">
      <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M8 1l6 3v4c0 4-2.7 6.5-6 7-3.3-.5-6-3-6-7V4l6-3z"/></svg>
      Permission requested
    </div>
    <div class="pdesc">Claude wants to run <code>${escapeHtml(event.tool)}</code></div>
    <div class="permission-actions">
      <button class="pbtn allow" data-action="allow">Allow once</button>
      <button class="pbtn allow-all" data-action="allowAll">Always allow ${event.tool}</button>
      <button class="pbtn deny" data-action="deny">Deny</button>
    </div>
  `;

  card.querySelectorAll('.pbtn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const action = btn.dataset.action;
      card.style.opacity = '0.6';
      card.querySelectorAll('.pbtn').forEach(b => b.disabled = true);

      const endpoint = document.getElementById('endpoint-input').value;
      await sendApprovalResponse(endpoint, event.request_id, action);

      const result = document.createElement('div');
      result.style.cssText = 'font-size:11px;color:var(--ok);margin-top:6px;';
      result.textContent = `→ ${btn.textContent}`;
      card.appendChild(result);

      setAwaitingApproval(false);
    });
  });

  bodyEl.appendChild(card);
}

function appendPlanningApprovalCard(bodyEl, plan) {
  if (bodyEl.querySelector('.planning-approval-card')) return;

  const card = document.createElement('div');
  card.className = 'planning-approval-card';
  card.innerHTML = `
    <div class="ptitle">
      <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M8 1l6 3v4c0 4-2.7 6.5-6 7-3.3-.5-6-3-6-7V4l6-3z"/></svg>
      Plan ready for review
    </div>
    <div class="plan-content">${escapeHtml(plan)}</div>
    <div class="permission-actions">
      <button class="pbtn allow-all" data-action="proceed">Proceed with plan</button>
      <button class="pbtn deny" data-action="revise">Ask to revise</button>
    </div>
  `;

  card.querySelectorAll('.pbtn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const action = btn.dataset.action;
      card.style.opacity = '0.6';
      card.querySelectorAll('.pbtn').forEach(b => b.disabled = true);

      const result = document.createElement('div');
      result.style.cssText = `font-size:11px;color:${action === 'proceed' ? 'var(--ok)' : 'var(--warn)'};margin-top:6px;`;
      result.textContent = action === 'proceed' ? '→ Proceeding with execution' : '→ Requesting revision';
      card.appendChild(result);

      setAwaitingApproval(false);
    });
  });

  bodyEl.appendChild(card);
}

async function sendApprovalResponse(endpoint, requestId, action) {
  try {
    await fetch(`${endpoint}/v1/permissions/respond`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        request_id: requestId,
        approved: action !== 'deny',
        always: action === 'allowAll'
      })
    });
  } catch (err) {
    console.error('Failed to send approval:', err);
  }
}

function appendToolBlock(bodyEl, toolData) {
  const block = document.createElement('div');
  block.className = 'tool-block';
  block.dataset.toolId = toolData.id;
  block.innerHTML = `
    <div class="tool-header" data-toggle-tool>
      <svg class="chev open" width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 3l5 5-5 5"/></svg>
      <span class="tool-icon"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M4 1h6l3 3v10a1 1 0 01-1 1H4a1 1 0 01-1-1V2a1 1 0 011-1z"/><path d="M10 1v3h3"/></svg></span>
      <span class="tool-name">${escapeHtml(toolData.name)}</span>
      <span class="tool-target">${escapeHtml(toolData.target)}</span>
      <span class="tool-status ${toolData.status}">${toolData.status}</span>
    </div>
    <div class="tool-body">
      <div class="label">Input</div>
      <pre>${escapeHtml(JSON.stringify(toolData.input, null, 2))}</pre>
    </div>
  `;

  const header = block.querySelector('[data-toggle-tool]');
  header.addEventListener('click', () => {
    const body = header.nextElementSibling;
    const chev = header.querySelector('.chev');
    body.classList.toggle('hidden');
    chev.classList.toggle('open');
  });

  bodyEl.appendChild(block);
  return block;
}

function updateToolBlock(block, updates) {
  if (updates.status) {
    const badge = block.querySelector('.tool-status');
    badge.className = 'tool-status ' + updates.status;
    badge.textContent = updates.status;
  }
  if (updates.output) {
    const body = block.querySelector('.tool-body');
    if (!body.querySelector('.label:nth-of-type(2)')) {
      const label = document.createElement('div');
      label.className = 'label';
      label.textContent = updates.status === 'error' ? 'Error' : 'Output';
      const pre = document.createElement('pre');
      pre.textContent = typeof updates.output === 'string' ? updates.output : JSON.stringify(updates.output, null, 2);
      body.appendChild(label);
      body.appendChild(pre);
    }
  }
}

sendBtn.addEventListener('click', handleSend);
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
  if (e.key === 'Escape' && streaming) {
    setStreaming(false);
    streamStatus.textContent = 'interrupted';
  }
});

// ---------- max turns slider ----------
const maxTurns = document.getElementById('max-turns');
const maxTurnsVal = document.getElementById('max-turns-val');
maxTurns.addEventListener('input', () => maxTurnsVal.textContent = maxTurns.value);

// ---------- permission badge cycling ----------
document.querySelectorAll('#tool-perm-list .tool-perm').forEach(row => {
  const badge = row.querySelector('.perm-badge');
  const states = ['allow', 'ask', 'deny'];
  badge.addEventListener('click', async () => {
    let cur = states.indexOf(badge.classList[1]);
    badge.classList.remove(states[cur]);
    cur = (cur + 1) % states.length;
    badge.classList.add(states[cur]);
    badge.textContent = states[cur];

    if (!activeSessionId) return;
    const endpoint = document.getElementById('endpoint-input').value;
    try {
      await fetch(`${endpoint}/v1/sessions/${activeSessionId}/tool-rule`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: activeSessionId,
          tool_name: row.dataset.tool,
          rule: states[cur]
        })
      });
      addLogLine('info', `tool rule updated: ${row.dataset.tool} → ${states[cur]}`);
    } catch (e) {
      addLogLine('error', `failed to update tool rule: ${e.message}`);
    }
  });
});

// ---------- permission mode select ----------
document.getElementById('perm-mode-select').addEventListener('change', async (e) => {
  const mode = e.target.value;
  if (!activeSessionId) return;
  const endpoint = document.getElementById('endpoint-input').value;
  try {
    await fetch(`${endpoint}/v1/sessions/${activeSessionId}/permission-mode`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: activeSessionId, permission_mode: mode })
    });
    addLogLine('info', `permission mode → ${mode}`);
  } catch (err) {
    addLogLine('error', `failed to set permission mode: ${err.message}`);
  }
});

// ---------- model select ----------
document.getElementById('model-select').addEventListener('change', async (e) => {
  const model = e.target.value;
  if (!activeSessionId) return;
  const endpoint = document.getElementById('endpoint-input').value;
  try {
    await fetch(`${endpoint}/v1/sessions/${activeSessionId}/model`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: activeSessionId, model })
    });
    addLogLine('info', `model → ${model}`);
  } catch (err) {
    addLogLine('error', `failed to set model: ${err.message}`);
  }
});

// ---------- mobile sidebar toggle ----------
document.getElementById('mobile-toggle').addEventListener('click', () => {
  document.getElementById('sidebar').classList.toggle('open');
});

// ---------- init: load persisted sessions on page load ----------
window.addEventListener('DOMContentLoaded', loadSessionList);
