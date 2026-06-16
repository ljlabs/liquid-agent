export function getEndpoint() {
  return document.getElementById('endpoint-input').value;
}

export function escapeHtml(s) {
  if (s === undefined || s === null) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export function formatTimeAgo(ts) {
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return 'now';
  if (diff < 3600) return Math.floor(diff / 60) + 'm';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h';
  return Math.floor(diff / 86400) + 'd';
}

export function scrollToBottom() {
  const conversation = document.getElementById('conversation');
  if (conversation) {
    conversation.scrollTop = conversation.scrollHeight;
  }
}

export function addLogLine(level, text) {
  const logsTab = document.querySelector('[data-rp-content="logs"]');
  if (!logsTab) return;
  const line = document.createElement('div');
  line.className = `log-line ${level}`;
  line.innerHTML = `<span class="lvl">${level === 'error' ? '✕' : level === 'warn' ? '!' : 'i'}</span><span class="ts">${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'})}</span><span>${escapeHtml(text)}</span>`;
  logsTab.appendChild(line);
  logsTab.scrollTop = logsTab.scrollHeight;
}
