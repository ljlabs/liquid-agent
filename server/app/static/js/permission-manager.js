import { escapeHtml, addLogLine } from './utils.js';
import { dbFetch } from './api.js';
import { state } from './state.js';

let toolPermHandlers = [];

export function renderToolPerms(tools) {
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

      if (!state.activeSessionId) {
        addLogLine('warn', `tool rule for ${row.dataset.tool} updated locally only (no active session)`);
        return;
      }
      try {
        await dbFetch(`/v1/sessions/${state.activeSessionId}/tool-rule`, {
          method: 'POST',
          body: JSON.stringify({
            session_id: state.activeSessionId,
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

export async function loadToolDefaults() {
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

export async function loadSessionToolRules(sessionId) {
  try {
    const data = await dbFetch(`/v1/sessions/${sessionId}/tool-rules`);
    renderToolPerms(data.rules);
  } catch (e) {
    console.warn('No session rules, using defaults:', e);
    await loadToolDefaults();
  }
}
