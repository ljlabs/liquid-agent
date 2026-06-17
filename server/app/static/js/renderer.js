/**
 * renderer.js - Pure renderer, no business logic.
 *
 * Receives ViewData objects and renders them to the DOM.
 * The ONLY place that touches the DOM for view updates.
 */

import { state } from './state.js';
import { escapeHtml, scrollToBottom } from './utils.js';
import {
  appendUserMessage,
  appendAssistantStub,
  appendOrUpdateThinking,
  appendToolBlock,
  updateToolBlock,
  appendPermissionCard,
} from './ui-components.js';
import { sendAction, switchStream } from './stream.js';

let lastMessagesHash = '';

/**
 * Render a ViewData object to the DOM.
 */
export function renderViewData(viewData) {
  if (!viewData || viewData.type !== 'view') return;

  renderSessionList(viewData.sessions || []);

  if (viewData.active_session) {
    renderActiveSession(viewData.active_session);
  }

  if (viewData.messages) {
    renderMessages(viewData.messages);
  }

  renderUIState(viewData.ui_state || {});

  renderPendingActions(viewData.pending_actions || [], viewData.active_session?.id);

  renderToolRules(viewData.tool_rules || []);

  renderModelDropdown(viewData.available_models || [], viewData.active_session?.model);
}

function renderSessionList(sessions) {
  const list = document.getElementById('session-list');
  if (!list) return;
  list.innerHTML = '';

  for (const session of sessions) {
    const item = document.createElement('div');
    item.className = 'session-item';
    if (session.id === state.activeSessionId) {
      item.classList.add('active');
    }
    item.dataset.session = session.id;

    const ago = formatTimeAgo(session.updated_at);
    item.innerHTML = `
      <span class="dot"></span>
      <span class="title">${escapeHtml(session.title)}</span>
      <span class="meta">${ago}</span>
    `;
    item.addEventListener('click', () => {
      switchStream(session.id);
    });
    list.appendChild(item);
  }
}

function renderActiveSession(session) {
  state.activeSessionId = session.id;

  const idTag = document.getElementById('session-id-tag');
  if (idTag) idTag.textContent = session.id;

  const titleEl = document.getElementById('session-title');
  if (titleEl) titleEl.textContent = session.title || 'Session';

  const cwdDisplay = document.getElementById('cwd-display');
  if (cwdDisplay) cwdDisplay.textContent = session.cwd || '';

  const cwdInput = document.getElementById('cwd-input');
  if (cwdInput) cwdInput.value = session.cwd || '';

  const turnTag = document.getElementById('turn-tag');
  if (turnTag) turnTag.textContent = `Turn ${session.turn_count || 0}`;

  const permSelect = document.getElementById('perm-mode-select');
  if (permSelect) permSelect.value = session.permission_mode || 'default';

  const modelSelect = document.getElementById('model-select');
  if (modelSelect && session.model) modelSelect.value = session.model;
}

function renderMessages(messages) {
  const newHash = JSON.stringify(messages.map(m => `${m.id}:${m.role}:${m.type}:${m.status}`));
  if (newHash === lastMessagesHash) return;
  lastMessagesHash = newHash;

  const conversation = document.getElementById('conversation');
  if (!conversation) return;
  conversation.innerHTML = '';

  for (const msg of messages) {
    if (msg.role === 'user') {
      renderUserMessage(msg);
    } else if (msg.role === 'assistant') {
      renderAssistantMessage(msg);
    } else if (msg.role === 'tool') {
      renderToolMessage(msg);
    }
  }

  scrollToBottom();
}

function renderUserMessage(msg) {
  const conversation = document.getElementById('conversation');
  const div = document.createElement('div');
  div.className = 'msg user';
  div.innerHTML = `<div class="avatar">U</div><div class="msg-body">
    <div class="msg-meta"><span class="role">You</span><span>${formatTime(msg.created_at)}</span></div>
    <div class="msg-content markdown-body"></div></div>`;
  div.querySelector('.msg-content').innerHTML = marked.parse(msg.content || '');
  conversation.appendChild(div);
}

function renderAssistantMessage(msg) {
  const conversation = document.getElementById('conversation');
  const div = document.createElement('div');
  div.className = 'msg assistant';
  div.innerHTML = `<div class="avatar">A</div><div class="msg-body">
    <div class="msg-meta"><span class="role">Claude</span><span>${formatTime(msg.created_at)}</span></div></div>`;
  const bodyEl = div.querySelector('.msg-body');

  if (msg.content_blocks && msg.content_blocks.length > 0) {
    for (const block of msg.content_blocks) {
      if (block.type === 'thinking') {
        const thinkBlock = document.createElement('div');
        thinkBlock.className = 'thinking-block collapsed';
        thinkBlock.innerHTML = `
          <div class="tlabel">
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="8" cy="8" r="6"/><path d="M8 5v3l2 2"/></svg>
            Thinking
          </div>
          <div class="tbody"></div>`;
        thinkBlock.querySelector('.tbody').textContent = block.content;
        thinkBlock.addEventListener('click', () => thinkBlock.classList.toggle('collapsed'));
        bodyEl.appendChild(thinkBlock);
      } else if (block.type === 'text') {
        const contentEl = document.createElement('div');
        contentEl.className = 'msg-content markdown-body rendered';
        contentEl.innerHTML = marked.parse(block.content || '');
        bodyEl.appendChild(contentEl);
      }
    }
  } else if (msg.content) {
    const contentEl = document.createElement('div');
    contentEl.className = 'msg-content markdown-body rendered';
    contentEl.innerHTML = marked.parse(msg.content);
    bodyEl.appendChild(contentEl);
  }

  if (msg.tool_name) {
    let input = msg.tool_input || {};
    if (typeof input === 'string') {
      try { input = JSON.parse(input); } catch (_) {}
    }
    appendToolBlock(bodyEl, {
      id: msg.tool_id || `msg_${msg.id}`,
      name: msg.tool_name,
      target: String(input.path || input.command || '').slice(0, 60),
      status: msg.status || 'success',
      input: input,
      pendingRequestId: msg.status === 'pending_approval' ? `perm_${msg.id}` : null,
    });
  }

  conversation.appendChild(div);
}

function renderToolMessage(msg) {
  const conversation = document.getElementById('conversation');
  const lastAssistant = conversation.querySelector('.msg.assistant:last-of-type');
  if (!lastAssistant) return;

  const bodyEl = lastAssistant.querySelector('.msg-body');
  const toolBlock = bodyEl.querySelector(`[data-tool-id="${msg.tool_id}"]`);
  if (toolBlock) {
    updateToolBlock(toolBlock, {
      status: msg.type === 'tool_error' ? 'error' : 'success',
      output: msg.content,
    });
  }
}

function renderUIState(uiState) {
  state.streaming = uiState.streaming || false;
  state.awaitingApproval = uiState.awaiting_approval || false;

  const sendBtn = document.getElementById('send-btn');
  if (sendBtn) {
    if (uiState.streaming) {
      sendBtn.classList.add('stop');
      sendBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor"><rect x="3" y="3" width="10" height="10" rx="1"/></svg>';
    } else {
      sendBtn.classList.remove('stop');
      sendBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M2 2l12 6-12 6 3-6-3-6z"/></svg>';
    }
  }

  const streamStatus = document.getElementById('stream-status');
  if (streamStatus) {
    if (uiState.streaming) {
      streamStatus.textContent = 'streaming\u2026';
    } else if (uiState.awaiting_approval) {
      streamStatus.textContent = 'awaiting approval\u2026';
    } else {
      streamStatus.textContent = 'idle';
    }
  }

  const input = document.getElementById('prompt-input');
  if (input) {
    input.disabled = uiState.awaiting_approval || false;
  }
  if (sendBtn) {
    sendBtn.disabled = uiState.awaiting_approval || false;
  }

  state.modeState.current = uiState.mode || 'default';
  const modePill = document.getElementById('mode-pill');
  if (modePill) {
    const modes = [
      { cls: 'active-plan', label: 'Plan mode', icon: '<path d="M3 3h10v10H3z"/><path d="M3 6.5h10M6.5 3v10"/>' },
      { cls: 'active-accept', label: 'Auto-accept edits', icon: '<path d="M3 8l3 3 7-7"/>' },
      { cls: '', label: 'Default mode', icon: '<circle cx="8" cy="8" r="5"/>' },
    ];
    const modeMap = { plan: 0, acceptEdits: 1, default: 2 };
    const idx = modeMap[uiState.mode] ?? 2;
    const m = modes[idx];
    modePill.className = 'mode-pill ' + m.cls;
    modePill.querySelector('svg').innerHTML = m.icon;
    modePill.childNodes[modePill.childNodes.length - 1].textContent = ' ' + m.label;
  }
}

function renderPendingActions(actions, sessionId) {
  document.querySelectorAll('.permission-card').forEach(el => el.remove());

  if (actions.length === 0) return;

  const conversation = document.getElementById('conversation');
  if (!conversation) return;
  const lastMsg = conversation.querySelector('.msg:last-child');
  if (!lastMsg) return;

  const bodyEl = lastMsg.querySelector('.msg-body') || lastMsg;

  for (const action of actions) {
    if (action.action_type === 'permission') {
      appendPermissionCard(bodyEl, {
        request_id: action.request_id,
        tool: action.tool_name,
        tool_input: action.tool_input,
      }, () => {});
    }
  }

  scrollToBottom();
}

function renderToolRules(rules) {
  const list = document.getElementById('tool-perm-list');
  if (!list) return;
  list.innerHTML = '';

  for (const rule of rules) {
    const row = document.createElement('div');
    row.className = 'tool-perm';
    row.dataset.tool = rule.tool;
    row.innerHTML = `<span class="name">${escapeHtml(rule.tool)}</span><span class="perm-badge ${rule.rule}">${rule.rule}</span>`;
    list.appendChild(row);
  }

  list.querySelectorAll('.tool-perm').forEach(row => {
    const badge = row.querySelector('.perm-badge');
    badge.addEventListener('click', async () => {
      const states = ['allow', 'ask', 'deny'];
      let cur = states.indexOf(badge.classList[1]);
      badge.classList.remove(states[cur]);
      cur = (cur + 1) % states.length;
      badge.classList.add(states[cur]);
      badge.textContent = states[cur];

      if (!state.activeSessionId) return;

      await sendAction({
        action: 'update_tool_rule',
        session_id: state.activeSessionId,
        tool_name: row.dataset.tool,
        tool_rule: states[cur],
      });
    });
  });
}

function renderModelDropdown(models, currentModel) {
  const select = document.getElementById('model-select');
  if (!select || models.length === 0) return;

  select.innerHTML = '';

  for (const model of models) {
    const option = document.createElement('option');
    option.value = model;
    option.textContent = model;
    if (model === currentModel) {
      option.selected = true;
    }
    select.appendChild(option);
  }

  // Ensure a model is always selected
  if (!select.value && models.length > 0) {
    select.value = models[0];
  }
}

function formatTimeAgo(ts) {
  if (!ts) return '';
  const diff = (Date.now() / 1000) - ts;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function formatTime(ts) {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
