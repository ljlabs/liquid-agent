/**
 * app.js - Minimal wiring. All business logic is in the backend.
 */

import { state } from './state.js';
import { connectViewStream, sendAction, getLastActiveSession } from './stream.js';

// ── Init ──────────────────────────────────────────────────────────

window.addEventListener('DOMContentLoaded', () => {
  connectViewStream();

  const lastSession = getLastActiveSession();
  if (lastSession) {
    sendAction({ action: 'get_view', session_id: lastSession });
  }
});

// ── Send message ──────────────────────────────────────────────────

async function handleSend() {
  if (state.streaming) {
    await sendAction({ action: 'interrupt', session_id: state.activeSessionId });
    return;
  }

  const input = document.getElementById('prompt-input');
  const text = input.value.trim();
  if (!text) return;

  const conversation = document.getElementById('conversation');
  if (conversation) {
    conversation.dataset.hash = '';
  }

  await sendAction({
    action: 'send_message',
    session_id: state.activeSessionId,
    message: text,
  });

  input.value = '';
  input.style.height = 'auto';
  document.getElementById('char-count').textContent = '0';
}

document.getElementById('send-btn').addEventListener('click', handleSend);

const input = document.getElementById('prompt-input');
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
  if (e.key === 'Escape' && state.streaming) {
    sendAction({ action: 'interrupt', session_id: state.activeSessionId });
  }
});

// ── Textarea autosize ─────────────────────────────────────────────

input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 160) + 'px';
  document.getElementById('char-count').textContent = input.value.length;

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

// ── New session ───────────────────────────────────────────────────

document.getElementById('new-session').addEventListener('click', () => {
  const model = document.getElementById('model-select').value;
  sendAction({ action: 'create_session', model: model });
});

// ── Permission mode cycle ─────────────────────────────────────────

const modePill = document.getElementById('mode-pill');
modePill.addEventListener('click', async () => {
  const modes = ['plan', 'acceptEdits', 'default'];
  const currentIdx = modes.indexOf(state.modeState.current);
  const nextMode = modes[(currentIdx + 1) % modes.length];

  state.modeState.current = nextMode;

  if (state.activeSessionId) {
    await sendAction({
      action: 'set_mode',
      session_id: state.activeSessionId,
      permission_mode: nextMode,
    });
  }
});

// ── Permission mode dropdown ──────────────────────────────────────

document.getElementById('perm-mode-select').addEventListener('change', async (e) => {
  if (!state.activeSessionId) return;
  await sendAction({
    action: 'set_mode',
    session_id: state.activeSessionId,
    permission_mode: e.target.value,
  });
});

// ── Model dropdown ────────────────────────────────────────────────

document.getElementById('model-select').addEventListener('change', async (e) => {
  if (!state.activeSessionId) return;
  await sendAction({
    action: 'set_model',
    session_id: state.activeSessionId,
    model: e.target.value,
  });
});

// ── Sidebar toggle ────────────────────────────────────────────────

document.getElementById('mobile-toggle').addEventListener('click', () => {
  document.getElementById('sidebar').classList.toggle('open');
});

// ── Collapsible sections ──────────────────────────────────────────

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

  const outToggle = e.target.closest('.tool-output-header');
  if (outToggle) {
    const outBody = outToggle.nextElementSibling;
    outBody.classList.toggle('hidden');
    outToggle.querySelector('.chev').classList.toggle('open');
    return;
  }
});

// ── Right panel tabs ──────────────────────────────────────────────

document.querySelectorAll('.rp-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.rp-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.rp-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    document.querySelector(`[data-rp-content="${tab.dataset.rpTab}"]`).classList.add('active');
  });
});

// ── Max turns slider ──────────────────────────────────────────────

const maxTurns = document.getElementById('max-turns');
const maxTurnsVal = document.getElementById('max-turns-val');
if (maxTurns && maxTurnsVal) {
  maxTurns.addEventListener('input', () => maxTurnsVal.textContent = maxTurns.value);
}
