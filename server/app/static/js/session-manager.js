import { state } from './state.js';
import { dbFetch, fetchPendingPermissions } from './api.js';
import { escapeHtml, formatTimeAgo } from './utils.js';
import { loadSessionToolRules } from './permission-manager.js';
import { appendUserMessage, appendAssistantStub, appendOrUpdateThinking, appendToolBlock, updateToolBlock, appendPermissionCard } from './ui-components.js';
import { setAwaitingApproval } from './stream-handler.js';

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
    let lastRole = null;

    for (const msg of data.messages) {
      console.log('[loadSession] Processing message:', msg.role, msg.type, msg.content?.substring(0, 50));
      
      if (msg.role === 'user') {
        // New user message = new conversation turn
        currentAssistantEl = null;
        appendUserMessage(msg.content);
      } else if (msg.role === 'assistant') {
        // Each assistant message creates a NEW message bubble
        // This ensures multi-turn conversations are properly separated
        currentAssistantEl = appendAssistantStub();
        currentAssistantEl.querySelector('.cursor-blink')?.remove();
        
        const bodyEl = currentAssistantEl.querySelector('.msg-body');
        lastRole = msg.role;

        if (msg.type === 'text' && msg.content) {
          // Ensure there's a content element for thinking blocks to insert before
          let contentEl = bodyEl.querySelector('.msg-content');
          if (!contentEl) {
            contentEl = document.createElement('div');
            contentEl.className = 'msg-content markdown-body rendered';
            bodyEl.appendChild(contentEl);
          }
          
          // Parse thinking tags from stored content
          const thoughtRegex = /<thought>([\s\S]*?)<\/thought>/g;
          let cleanedContent = msg.content;
          let match;
          
          while ((match = thoughtRegex.exec(msg.content)) !== null) {
            // Create thinking block for each thought found
            appendOrUpdateThinking(currentAssistantEl, { data: match[1], done: true });
            // Remove thought tags from content
            cleanedContent = cleanedContent.replace(match[0], '');
          }
          
          // Only add content element if there's non-thinking content
          if (cleanedContent.trim()) {
            contentEl.innerHTML = marked.parse(cleanedContent.trim());
          }
        } else if (msg.type === 'thinking' && msg.content) {
          appendOrUpdateThinking(currentAssistantEl, { data: msg.content, done: true });
        } else if (msg.type === 'tool_use') {
          let input = {};
          try { input = JSON.parse(msg.tool_input || '{}'); } catch (_) {}
          const toolStatus = msg.pending_request_id ? 'pending_approval' : 'running';
          appendToolBlock(bodyEl, {
            id: msg.tool_id || `hist_${msg.id}`,
            name: msg.tool_name || 'Tool',
            target: String(input.path || input.command || '').slice(0, 60),
            status: toolStatus,
            input,
          });
        }
      } else if (msg.role === 'tool') {
        // Tool messages should be attached to the previous assistant message
        if (!currentAssistantEl) {
          console.warn('[loadSession] Skipping tool message - no assistant context:', msg);
          continue;
        }
        
        const bodyEl = currentAssistantEl.querySelector('.msg-body');
        lastRole = msg.role;

        if (msg.type === 'tool_result' || msg.type === 'tool_error') {
          const toolBlock = bodyEl.querySelector(`[data-tool-id="${msg.tool_id}"]`);
          if (toolBlock) {
            updateToolBlock(toolBlock, {
              status: msg.type === 'tool_error' ? 'error' : 'success',
              output: msg.content,
            });
          }
          // After tool results, the NEXT assistant message will create a new bubble
          // (because each assistant message creates a new bubble)
        }
      }
    }

    // Check for pending permissions after loading messages
    const pendingPermissions = await fetchPendingPermissions(sessionId);
    if (pendingPermissions.length > 0) {
      console.log('[loadSession] Found pending permissions:', pendingPermissions.length);
      state.pendingPermissions = pendingPermissions;
      
      // Find the last assistant message element to append permission cards
      const conversation = document.getElementById('conversation');
      const lastAssistantMsg = conversation.querySelector('.msg.assistant:last-of-type');
      
      if (lastAssistantMsg) {
        const bodyEl = lastAssistantMsg.querySelector('.msg-body');
        for (const perm of pendingPermissions) {
          // Map database fields to the format appendPermissionCard expects
          const permEvent = {
            request_id: perm.request_id,
            tool: perm.tool_name,
            tool_input: perm.tool_input ? JSON.parse(perm.tool_input) : {},
          };
          appendPermissionCard(bodyEl, permEvent, () => {
            setAwaitingApproval(false);
            // Remove from pending list
            state.pendingPermissions = state.pendingPermissions.filter(p => p.request_id !== perm.request_id);
          });
        }
        setAwaitingApproval(true);
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
        model: document.getElementById('model-select')?.value || 'gemma-4-31b',
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