import { state } from './state.js';
import { dbFetch } from './api.js';
import { escapeHtml, formatTimeAgo } from './utils.js';
import { loadSessionToolRules } from './permission-manager.js';
import { appendUserMessage, appendAssistantStub, appendOrUpdateThinking, appendToolBlock, updateToolBlock } from './ui-components.js';

export async function loadSessionList() {
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

export async function switchToSession(sessionId, title, clickedItem) {
  state.activeSessionId = sessionId;
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

export async function createNewSession() {
  try {
    const data = await dbFetch('/v1/sessions', {
      method: 'POST',
      body: JSON.stringify({
        cwd: document.getElementById('cwd-input')?.value || '',
        model: document.getElementById('model-select')?.value || 'claude-sonnet-4-6',
      }),
    });

    const sessionId = data.session_id;

    state.activeSessionId = sessionId;
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
