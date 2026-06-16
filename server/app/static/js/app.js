import { state } from './state.js';
import { getEndpoint, addLogLine } from './utils.js';
import { dbFetch } from './api.js';
import { appendUserMessage } from './ui-components.js';
import { loadSessionList, createNewSession } from './session-manager.js';
import { loadToolDefaults } from './permission-manager.js';
import { setStreaming, sendToWrapper } from './stream-handler.js';

// ---------- delegated toggle clicks ----------
document.addEventListener('click', (e) => {
  const sidebarToggle = e.target.closest('[data-toggle]');
  if (sidebarToggle) {
    sidebarToggle.parentElement.classList.toggle('collapsed');
    return;
  }

  const toolToggle = e.target.closest('[data-toggle-tool]');
  if (toolToggle) {
    const body = toolToggle.nextElementSibling;
    const chev = toolToggle.querySelector('.chev');
    body.classList.toggle('hidden');
    chev.classList.toggle('open');
    return;
  }

  const thinkToggle = e.target.closest('[data-toggle-think]');
  if (thinkToggle) {
    thinkToggle.classList.toggle('collapsed');
    return;
  }

  const outToggle = e.target.closest('.tool-output-header');
  if (outToggle) {
    const outBody = outToggle.nextElementSibling;
    outBody.classList.toggle('hidden');
    outToggle.querySelector('.chev').classList.toggle('open');
    return;
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
  { cls: 'active-accept', label: 'Auto-accept edits', icon: '<path d="M3 8l3 3 7-7"/>', state: 'acceptEdits' },
  { cls: '', label: 'Default mode', icon: '<circle cx="8" cy="8" r="5"/>', state: 'default' }
];

const modePill = document.getElementById('mode-pill');
modePill.addEventListener('click', async () => {
  state.modeIdx = (state.modeIdx + 1) % modes.length;
  const m = modes[state.modeIdx];
  state.modeState.current = m.state;
  modePill.className = 'mode-pill ' + m.cls;
  modePill.querySelector('svg').innerHTML = m.icon;
  modePill.childNodes[modePill.childNodes.length - 1].textContent = ' ' + m.label;

  // Sync with server if there's an active session
  if (state.activeSessionId) {
    try {
      await dbFetch(`/v1/sessions/${state.activeSessionId}/permission-mode`, {
        method: 'POST',
        body: JSON.stringify({ session_id: state.activeSessionId, permission_mode: m.state })
      });
      // Also update the dropdown if it exists to keep UI in sync
      const select = document.getElementById('perm-mode-select');
      if (select) select.value = m.state;
      addLogLine('info', `permission mode → ${m.state}`);
    } catch (err) {
      addLogLine('error', `failed to sync permission mode: ${err.message}`);
    }
  }
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

document.querySelectorAll('.slash-item').forEach(item => {
  item.addEventListener('click', () => {
    input.value = item.querySelector('.cmd').textContent + ' ';
    document.getElementById('slash-menu').classList.remove('open');
    input.focus();
  });
});

async function handleSend() {
  if (state.streaming) {
    if (state.currentStreamAbortController) {
      state.currentStreamAbortController.abort();
    }
    setStreaming(false);
    document.getElementById('stream-status').textContent = 'interrupted';
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
  const mode = state.modeState.current;

  await sendToWrapper(endpoint, model, text, { planning: mode === 'plan' });
}

document.getElementById('send-btn').addEventListener('click', handleSend);
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
  if (e.key === 'Escape' && state.streaming) {
    setStreaming(false);
    document.getElementById('stream-status').textContent = 'interrupted';
  }
});

document.getElementById('new-session').addEventListener('click', createNewSession);

const maxTurns = document.getElementById('max-turns');
const maxTurnsVal = document.getElementById('max-turns-val');
maxTurns.addEventListener('input', () => maxTurnsVal.textContent = maxTurns.value);

document.getElementById('perm-mode-select').addEventListener('change', async (e) => {
  const mode = e.target.value;
  if (!state.activeSessionId) return;
  try {
    await dbFetch(`/v1/sessions/${state.activeSessionId}/permission-mode`, {
      method: 'POST',
      body: JSON.stringify({ session_id: state.activeSessionId, permission_mode: mode })
    });
    addLogLine('info', `permission mode → ${mode}`);
  } catch (err) {
    addLogLine('error', `failed to set permission mode: ${err.message}`);
  }
});

document.getElementById('model-select').addEventListener('change', async (e) => {
  const model = e.target.value;
  if (!state.activeSessionId) return;
  try {
    await dbFetch(`/v1/sessions/${state.activeSessionId}/model`, {
      method: 'POST',
      body: JSON.stringify({ session_id: state.activeSessionId, model })
    });
    addLogLine('info', `model → ${model}`);
  } catch (err) {
    addLogLine('error', `failed to set model: ${err.message}`);
  }
});

document.getElementById('mobile-toggle').addEventListener('click', () => {
  document.getElementById('sidebar').classList.toggle('open');
});

window.addEventListener('DOMContentLoaded', () => {
  loadSessionList();
  loadToolDefaults();
});
