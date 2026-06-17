import { escapeHtml, scrollToBottom } from './utils.js';
import { sendApprovalResponse } from './api.js';
import { state } from './state.js';

export function appendUserMessage(text) {
  const conversation = document.getElementById('conversation');
  const div = document.createElement('div');
  div.className = 'msg user';
  div.innerHTML = `<div class="avatar">U</div><div class="msg-body">
    <div class="msg-meta"><span class="role">You</span><span>${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</span></div>
    <div class="msg-content markdown-body"></div></div>`;
  div.querySelector('.msg-content').innerHTML = marked.parse(text);
  conversation.appendChild(div);
  scrollToBottom();
}

export function appendAssistantStub() {
  const conversation = document.getElementById('conversation');
  const div = document.createElement('div');
  div.className = 'msg assistant';
  div.innerHTML = `<div class="avatar">A</div><div class="msg-body">
    <div class="msg-meta"><span class="role">Claude</span><span>${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</span></div>
    <div class="msg-content markdown-body"><span class="cursor-blink"></span></div></div>`;
  conversation.appendChild(div);
  scrollToBottom();
  return div;
}

export function appendOrUpdateThinking(msgEl, event) {
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

export function appendToolBlock(bodyEl, toolData) {
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

export function updateToolBlock(block, updates) {
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

export function appendPermissionCard(bodyEl, event, onRespond) {
  const card = document.createElement('div');
  card.className = 'permission-card';
  card.dataset.requestId = event.request_id;
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

      if (onRespond) onRespond();
    });
  });

  bodyEl.appendChild(card);
}

export function appendPlanningApprovalCard(bodyEl, plan, onRespond) {
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

      if (onRespond) onRespond();
    });
  });

  bodyEl.appendChild(card);
}
