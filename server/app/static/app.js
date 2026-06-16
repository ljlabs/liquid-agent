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

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ---------- delegated toggle clicks ----------
// Consolidates sidebar, tool block, thinking block, and tool output toggles
document.addEventListener('click', (e) => {
  // Sidebar section toggle
  const sidebarToggle = e.target.closest('[data-toggle]');
  if (sidebarToggle) {
    sidebarToggle.parentElement.classList.toggle('collapsed');
    return;
  }

  // Tool block toggle
  const toolToggle = e.target.closest('[data-toggle-tool]');
  if (toolToggle) {
    const body = toolToggle.nextElementSibling;
    const chev = toolToggle.querySelector('.chev');
    body.classList.toggle('hidden');
    chev.classList.toggle('open');
    return;
  }

  // Thinking block toggle
  const thinkToggle = e.target.closest('[data-toggle-think]');
  if (thinkToggle) {
    thinkToggle.classList.toggle('collapsed');
    return;
  }

  // Tool output toggle
  const outToggle = e.target.closest('.tool-output-header');
  if (outToggle) {
    const outBody = outToggle.nextElementSibling;
    outBody.classList.toggle('hidden');
    outToggle.querySelector('.chev').classList.toggle('open');
    return;
  }
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

  await loadSessionToolRules(sessionId);

  try {
    const data = await dbFetch(`/v1/db/sessions/${sessionId}/messages`);
    let currentAssistantEl = null;

    for (const msg of data.messages) {
      if (msg.role === 'user') {
        currentAssistantEl = null;
        appendUserMessage(msg.content);
      } else {
        if (!currentAssistantEl) {
          currentAssistantEl = appendAssistantStub();
          currentAssistantEl.querySelector('.cursor-blink')?.remove();
          currentAssistantEl.querySelector('.msg-content')?.remove();
        }
        const bodyEl = currentAssistantEl.querySelector('.msg-body');

        if (msg.type === 'text' && msg.content) {
          const contentEl = document.createElement('div');
          contentEl.className = 'msg-content markdown-body rendered';
          contentEl.innerHTML = marked.parse(msg.content);
          bodyEl.appendChild(contentEl);
        } else if (msg.type === 'thinking' && msg.content) {
          appendOrUpdateThinking(currentAssistantEl, { data: msg.content, done: true });
        } else if (msg.type === 'tool_use') {
          let input = {};
          try { input = JSON.parse(msg.tool_input || '{}'); } catch (_) {}
          appendToolBlock(bodyEl, {
            id: msg.tool_id || `hist_${msg.id}`,
            name: msg.tool_name || 'Tool',
            target: String(input.path || input.command || '').slice(0, 60),
            status: 'running',
            input,
          });
        } else if (msg.type === 'tool_result' || msg.type === 'tool_error') {
          const toolBlock = bodyEl.querySelector(`[data-tool-id="${msg.tool_id}"]`);
          if (toolBlock) {
            updateToolBlock(toolBlock, {
              status: msg.type === 'tool_error' ? 'error' : 'success',
              output: msg.content,
            });
          }
        }
      }
    }
  } catch (e) {
    console.error('Failed to load messages:', e);
  }
}

// ---------- new session ----------
async function createNewSession() {
  try {
    const data = await dbFetch('/v1/sessions', {
      method: 'POST',
      body: JSON.stringify({
        cwd: document.getElementById('cwd-input')?.value || '',
        model: document.getElementById('model-select')?.value || 'claude-sonnet-4-6',
      }),
    });

    const sessionId = data.session_id;

    activeSessionId = sessionId;
    document.getElementById('session-id-tag').textContent = sessionId;
    document.getElementById('turn-tag').textContent = 'Turn 0';
    document.getElementById('conversation').innerHTML = '';
    document.getElementById('prompt-input').focus();

    await loadSessionToolRules(sessionId);
    await loadSessionList();

    document.querySelectorAll('.session-item').forEach(item => {
      item.classList.toggle('active', item.dataset.session === sessionId);
    });

  } catch (e) {
    console.error('Failed to create new session:', e);
    alert('Failed to create session. Please check server connection.');
  }
}

document.getElementById('new-session').addEventListener('click', createNewSession);

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
    <div class="msg-content markdown-body"></div></div>`;
  div.querySelector('.msg-content').innerHTML = marked.parse(text);
  conversation.appendChild(div);
  scrollToBottom();
}

function appendAssistantStub() {
  const div = document.createElement('div');
  div.className = 'msg assistant';
  div.innerHTML = `<div class="avatar">A</div><div class="msg-body">
    <div class="msg-meta"><span class="role">Claude</span><span>${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</span></div>
    <div class="msg-content markdown-body"><span class="cursor-blink"></span></div></div>`;
  conversation.appendChild(div);
  scrollToBottom();
  return div;
}

function appendAssistantMessage(text) {
  const div = document.createElement('div');
  div.className = 'msg assistant';
  div.innerHTML = `<div class="avatar">A</div><div class="msg-body">
    <div class="msg-meta"><span class="role">Claude</span><span></span></div>
    <div class="msg-content markdown-body"></div></div>`;
  
  renderAssistantContent(div, text);
  conversation.appendChild(div);
  scrollToBottom();
}

function processThoughts(msgEl, text) {
  const thoughtRegex = /<thought>([\s\S]*?)<\/thought>/g;
  let renderText = text;
  let match;
  while ((match = thoughtRegex.exec(text)) !== null) {
    appendOrUpdateThinking(msgEl, { data: match[1], done: true });
    renderText = renderText.replace(match[0], '');
  }
  return renderText.trim();
}

function renderAssistantContent(msgEl, fullText) {
  const contentEl = msgEl.querySelector('.msg-content');
  contentEl.innerHTML = '';
  const cleanText = processThoughts(msgEl, fullText);
  contentEl.innerHTML = marked.parse(cleanText);
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

  const endpoint = getEndpoint();
  const model = document.getElementById('model-select').value;
  const mode = modeState.current;

  await sendToWrapper(endpoint, model, text, { planning: mode === 'plan' });
}

async function sendToWrapper(endpoint, model, userMessage, options = {}) {
  currentStreamAbortController = new AbortController();
  const msgEl = appendAssistantStub();
  const contentEl = msgEl.querySelector('.msg-content');
  setStreaming(true);

  console.log('[sendToWrapper] Starting stream request', { endpoint, model, planning_mode: options.planning });

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

    console.log('[sendToWrapper] Stream response status:', response.status);

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let eventCount = 0;

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        console.log('[sendToWrapper] Stream complete, received', eventCount, 'events');
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;

        try {
          const event = JSON.parse(line.slice(6));
          eventCount++;
          handleStreamEvent(event, msgEl);
        } catch (e) {
          console.error('Failed to parse event:', e, 'line:', line);
        }
      }
    }

    setStreaming(false);
  } catch (err) {
    console.error('[sendToWrapper] Error:', err);
    if (err.name !== 'AbortError') {
      contentEl.innerHTML += `<div style="color:var(--err); margin-top:4px;">Error: ${escapeHtml(err.message)}</div>`;
    }
    setStreaming(false);
  }
}

function handleStreamEvent(event, msgEl) {
  const contentEl = msgEl.querySelector('.msg-content');
  const bodyEl = msgEl.querySelector('.msg-body');

  console.log('[SSE event]', event.type, event);

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
      loadSessionList();
      loadSessionToolRules(event.session_id);
      break;

    case 'text':
      let activeTextEl = bodyEl.querySelector('.msg-content.streaming-active');
      if (!activeTextEl) {
        const initialTextEl = bodyEl.querySelector('.msg-content');
        if (initialTextEl && !initialTextEl.classList.contains('rendered')) {
          activeTextEl = initialTextEl;
          activeTextEl.classList.add('streaming-active');
        } else {
          activeTextEl = document.createElement('div');
          activeTextEl.className = 'msg-content markdown-body streaming-active';
          bodyEl.appendChild(activeTextEl);
        }
      }

      let textVal = activeTextEl.dataset.fullText || '';
      textVal += event.data;
      activeTextEl.dataset.fullText = textVal;

      const renderText = processThoughts(msgEl, textVal);
      activeTextEl.innerHTML = marked.parse(renderText);

      // Keep cursor if not done
      if (!textVal.includes('</thought>') || textVal.split('</thought>').pop().trim() !== '') {
         if (!activeTextEl.querySelector('.cursor-blink')) {
           const span = document.createElement('span');
           span.className = 'cursor-blink';
           activeTextEl.appendChild(span);
         }
      }
      scrollToBottom();
      break;

    case 'thinking':
      appendOrUpdateThinking(msgEl, event);
      scrollToBottom();
      break;

    case 'tool_use':
      const currentActiveText = bodyEl.querySelector('.msg-content.streaming-active');
      if (currentActiveText) {
        currentActiveText.classList.remove('streaming-active');
        currentActiveText.classList.add('rendered');
        currentActiveText.querySelector('.cursor-blink')?.remove();
      }
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
        const fullTxt = Array.from(bodyEl.querySelectorAll('.msg-content')).map(el => el.textContent).join('\n');
        appendPlanningApprovalCard(bodyEl, event.plan || fullTxt);
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
      const errEl = bodyEl.querySelector('.msg-content.streaming-active') || bodyEl.querySelector('.msg-content') || bodyEl;
      errEl.innerHTML += `<div style="color:var(--err); margin-top:4px;">Error: ${escapeHtml(event.message)}</div>`;
      scrollToBottom();
      break;

    case 'done':
      const activeTextFinished = bodyEl.querySelector('.msg-content.streaming-active');
      if (activeTextFinished) {
        activeTextFinished.classList.remove('streaming-active');
        activeTextFinished.classList.add('rendered');
      }
      msgEl.querySelectorAll('.cursor-blink').forEach(c => c.remove());
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

      await sendApprovalResponse(event.request_id, action);

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

async function sendApprovalResponse(requestId, action) {
  try {
    await dbFetch('/v1/permissions/respond', {
      method: 'POST',
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

  bodyEl.appendChild(block);
  return block;
}

function updateToolBlock(block, updates) {
  if (updates.status) {
    const badge = block.querySelector('.tool-status');
    badge.className = 'tool-status ' + updates.status;
    badge.textContent = updates.status;
  }
  if (updates.output !== undefined && updates.output !== null) {
    const body = block.querySelector('.tool-body');
    if (!body.querySelector('.tool-output-section')) {
      const outputText = typeof updates.output === 'string'
        ? updates.output
        : JSON.stringify(updates.output, null, 2);
      const TRUNCATE = 500;
      const isTruncated = outputText.length > TRUNCATE;
      const truncated = isTruncated ? outputText.slice(0, TRUNCATE) : outputText;

      const section = document.createElement('div');
      section.className = 'tool-output-section';

      const outHeader = document.createElement('div');
      outHeader.className = 'tool-output-header';
      outHeader.innerHTML = `
        <svg class="chev" width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 3l5 5-5 5"/></svg>
        <span>${updates.status === 'error' ? 'Error' : 'Output'}</span>
      `;

      const outBody = document.createElement('div');
      outBody.className = 'tool-output-body hidden';

      const pre = document.createElement('pre');
      pre.className = 'tool-output-pre';
      pre.textContent = truncated;
      outBody.appendChild(pre);

      if (isTruncated) {
        const expandBtn = document.createElement('button');
        expandBtn.className = 'tool-output-expand';
        expandBtn.textContent = `Show full output (${outputText.length} chars)`;
        let expanded = false;
        expandBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          expanded = !expanded;
          pre.textContent = expanded ? outputText : truncated;
          expandBtn.textContent = expanded
            ? 'Collapse output'
            : `Show full output (${outputText.length} chars)`;
        });
        outBody.appendChild(expandBtn);
      }

      section.appendChild(outHeader);
      section.appendChild(outBody);
      body.appendChild(section);
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
let toolPermHandlers = [];

function renderToolPerms(tools) {
  const list = document.getElementById('tool-perm-list');
  if (!list) return;

  toolPermHandlers.forEach(({ row, handler }) => {
    const badge = row.querySelector('.perm-badge');
    if (badge) badge.removeEventListener('click', handler);
  });
  toolPermHandlers = [];

  list.innerHTML = '';
  for (const { tool, rule } of tools) {
    const row = document.createElement('div');
    row.className = 'tool-perm';
    row.dataset.tool = tool;
    row.innerHTML = `<span class="name">${escapeHtml(tool)}</span><span class="perm-badge ${rule}">${rule}</span>`;
    list.appendChild(row);
  }

  list.querySelectorAll('.tool-perm').forEach(row => {
    const badge = row.querySelector('.perm-badge');
    const handler = async () => {
      const states = ['allow', 'ask', 'deny'];
      let cur = states.indexOf(badge.classList[1]);
      badge.classList.remove(states[cur]);
      cur = (cur + 1) % states.length;
      badge.classList.add(states[cur]);
      badge.textContent = states[cur];

      if (!activeSessionId) {
        addLogLine('warn', `tool rule for ${row.dataset.tool} updated locally only (no active session)`);
        return;
      }
      try {
        await dbFetch(`/v1/sessions/${activeSessionId}/tool-rule`, {
          method: 'POST',
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
    };
    badge.addEventListener('click', handler);
    toolPermHandlers.push({ row, handler });
  });
}

async function loadToolDefaults() {
  try {
    const data = await dbFetch('/v1/tool-defaults');
    renderToolPerms(data.tools.map(tool => ({
      tool,
      rule: data.rules.find(r => r.tool === tool)?.rule || 'ask',
    })));
  } catch (e) {
    console.error('Failed to load tool defaults:', e);
  }
}

async function loadSessionToolRules(sessionId) {
  try {
    const data = await dbFetch(`/v1/sessions/${sessionId}/tool-rules`);
    renderToolPerms(data.rules);
  } catch (e) {
    console.warn('No session rules, using defaults:', e);
    await loadToolDefaults();
  }
}

// ---------- permission mode select ----------
document.getElementById('perm-mode-select').addEventListener('change', async (e) => {
  const mode = e.target.value;
  if (!activeSessionId) return;
  try {
    await dbFetch(`/v1/sessions/${activeSessionId}/permission-mode`, {
      method: 'POST',
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
  try {
    await dbFetch(`/v1/sessions/${activeSessionId}/model`, {
      method: 'POST',
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

// ---------- init: load persisted sessions and tool defaults on page load ----------
window.addEventListener('DOMContentLoaded', () => {
  loadSessionList();
  loadToolDefaults();
});