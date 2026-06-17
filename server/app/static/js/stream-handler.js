import { state } from './state.js';
import { getEndpoint, escapeHtml, scrollToBottom, addLogLine } from './utils.js';
import { appendAssistantStub, appendOrUpdateThinking, appendToolBlock, updateToolBlock, appendPermissionCard, appendPlanningApprovalCard } from './ui-components.js';
import { loadSessionList } from './session-manager.js';
import { loadSessionToolRules } from './permission-manager.js';

export function setStreaming(on) {
  const sendBtn = document.getElementById('send-btn');
  const streamStatus = document.getElementById('stream-status');
  state.streaming = on;
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

export function setAwaitingApproval(on) {
  const input = document.getElementById('prompt-input');
  const sendBtn = document.getElementById('send-btn');
  const streamStatus = document.getElementById('stream-status');
  state.awaitingApproval = on;
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

export async function sendToWrapper(endpoint, model, userMessage, options = {}) {
  state.currentStreamAbortController = new AbortController();
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
        session_id: state.activeSessionId,
        model,
        planning_mode: options.planning || false,
        auto_approve: state.modeState.current === 'acceptEdits'
      }),
      signal: state.currentStreamAbortController.signal
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

export function handleStreamEvent(event, msgEl) {
  const bodyEl = msgEl.querySelector('.msg-body');

  console.log('[SSE event]', event.type, event);

  switch (event.type) {
    case 'session':
      state.activeSessionId = event.session_id;
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
        // Always create a new text element for each response
        activeTextEl = document.createElement('div');
        activeTextEl.className = 'msg-content markdown-body streaming-active';
        bodyEl.appendChild(activeTextEl);
      }

      let textVal = activeTextEl.dataset.fullText || '';
      textVal += event.data;
      activeTextEl.dataset.fullText = textVal;

      const thoughtRegex = /<thought>([\s\S]*?)<\/thought>/g;
      let renderText = textVal;
      let match;
      while ((match = thoughtRegex.exec(textVal)) !== null) {
        appendOrUpdateThinking(msgEl, { data: match[1], done: true });
        renderText = renderText.replace(match[0], '');
      }
      
      activeTextEl.innerHTML = marked.parse(renderText.trim());

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
        status: event.pending_request_id ? 'pending_approval' : 'running',
        input: event.input || {},
        pendingRequestId: event.pending_request_id || null,
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
      state.pendingPermissions.push(event);
      setAwaitingApproval(true);
      appendPermissionCard(bodyEl, event, () => {
        setAwaitingApproval(false);
        state.pendingPermissions = state.pendingPermissions.filter(p => p.request_id !== event.request_id);
      });
      scrollToBottom();
      break;

    case 'planning_complete':
      if (state.modeState.current === 'plan') {
        setAwaitingApproval(true);
        const fullTxt = Array.from(bodyEl.querySelectorAll('.msg-content')).map(el => el.textContent).join('\n');
        appendPlanningApprovalCard(bodyEl, event.plan || fullTxt, () => setAwaitingApproval(false));
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

function finalizeAssistantMessage(msgEl, result) {
  const cursor = msgEl.querySelector('.cursor-blink');
  if (cursor) cursor.remove();

  if (result.is_error) {
    document.getElementById('stream-status').textContent = `error: ${result.stop_reason || 'unknown'}`;
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

export async function subscribeToSessionEvents(sessionId) {
  if (state.streaming) return;

  const endpoint = getEndpoint();
  const conversation = document.getElementById('conversation');
  let msgEl = conversation.querySelector('.msg.assistant:last-of-type');
  if (!msgEl) {
    msgEl = appendAssistantStub();
  }
  const bodyEl = msgEl.querySelector('.msg-body');
  setStreaming(true);

  try {
    const response = await fetch(`${endpoint}/v1/sessions/${sessionId}/events`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

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
          if (event.type === 'heartbeat') continue;
          handleStreamEvent(event, msgEl);
        } catch (e) {
          console.error('Failed to parse event:', e);
        }
      }
    }
  } catch (err) {
    console.error('[subscribeToSessionEvents] Error:', err);
  } finally {
    setStreaming(false);
  }
}
