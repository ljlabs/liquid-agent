import { describe, it, expect, vi, beforeEach } from 'vitest';
import { state } from '../state.js';
import { setStreaming, setAwaitingApproval, handleStreamEvent } from '../stream-handler.js';

beforeEach(() => {
  vi.clearAllMocks();
  document.getElementById('conversation').innerHTML = '';
  state.streaming = false;
  state.awaitingApproval = false;
  state.activeSessionId = null;
  state.pendingPermissions = [];
  document.getElementById('stream-status').textContent = 'idle';
  document.getElementById('prompt-input').disabled = false;
  document.getElementById('send-btn').disabled = false;
});

describe('setStreaming', () => {
  it('enables streaming state and UI', () => {
    setStreaming(true);
    expect(state.streaming).toBe(true);
    expect(document.getElementById('send-btn').classList.contains('stop')).toBe(true);
    expect(document.getElementById('stream-status').textContent).toBe('streaming…');
  });

  it('disables streaming state and UI', () => {
    setStreaming(true);
    setStreaming(false);
    expect(state.streaming).toBe(false);
    expect(document.getElementById('send-btn').classList.contains('stop')).toBe(false);
    expect(document.getElementById('stream-status').textContent).toBe('idle');
  });
});

describe('setAwaitingApproval', () => {
  it('disables input and send button when awaiting', () => {
    setAwaitingApproval(true);
    expect(state.awaitingApproval).toBe(true);
    expect(document.getElementById('prompt-input').disabled).toBe(true);
    expect(document.getElementById('send-btn').disabled).toBe(true);
    expect(document.getElementById('stream-status').textContent).toBe('awaiting approval…');
  });

  it('re-enables input and send button when resolved', () => {
    setAwaitingApproval(true);
    setAwaitingApproval(false);
    expect(state.awaitingApproval).toBe(false);
    expect(document.getElementById('prompt-input').disabled).toBe(false);
    expect(document.getElementById('send-btn').disabled).toBe(false);
    expect(document.getElementById('stream-status').textContent).toBe('idle');
  });
});

describe('handleStreamEvent', () => {
  function createMsgEl() {
    const div = document.createElement('div');
    div.className = 'msg assistant';
    div.innerHTML = '<div class="msg-body"><div class="msg-content markdown-body"></div></div>';
    return div;
  }

  it('handles session event', () => {
    const msgEl = createMsgEl();
    handleStreamEvent({
      type: 'session',
      session_id: 'sess_new',
      title: 'New Session',
      cwd: '/tmp',
    }, msgEl);

    expect(state.activeSessionId).toBe('sess_new');
    expect(document.getElementById('session-id-tag').textContent).toBe('sess_new');
    expect(document.getElementById('session-title').textContent).toBe('New Session');
    expect(document.getElementById('cwd-input').value).toBe('/tmp');
    expect(document.getElementById('cwd-display').textContent).toBe('/tmp');
  });

  it('handles text event', () => {
    const msgEl = createMsgEl();
    handleStreamEvent({ type: 'text', data: 'Hello ' }, msgEl);
    handleStreamEvent({ type: 'text', data: 'world' }, msgEl);

    const textEl = msgEl.querySelector('.streaming-active');
    expect(textEl).not.toBeNull();
    expect(textEl.textContent).toContain('Hello world');
  });

  it('handles thinking event', () => {
    const msgEl = createMsgEl();
    handleStreamEvent({ type: 'thinking', data: 'analyzing...' }, msgEl);

    const block = msgEl.querySelector('.thinking-block');
    expect(block).not.toBeNull();
    expect(block.classList.contains('streaming')).toBe(true);
    expect(block.querySelector('.tbody').textContent).toBe('analyzing...');
  });

  it('handles tool_use event', () => {
    const msgEl = createMsgEl();
    handleStreamEvent({
      type: 'tool_use',
      tool_id: 'tool_1',
      name: 'Bash',
      input: { command: 'pwd' },
    }, msgEl);

    const block = msgEl.querySelector('[data-tool-id="tool_1"]');
    expect(block).not.toBeNull();
    expect(block.querySelector('.tool-name').textContent).toBe('Bash');
    expect(block.querySelector('.tool-status').textContent).toBe('running');
  });

  it('handles tool_use with pending_request_id', () => {
    const msgEl = createMsgEl();
    handleStreamEvent({
      type: 'tool_use',
      tool_id: 'tool_1',
      name: 'Bash',
      input: { command: 'rm -rf /' },
      pending_request_id: 'perm_1',
    }, msgEl);

    const block = msgEl.querySelector('[data-tool-id="tool_1"]');
    expect(block.querySelector('.tool-status').textContent).toBe('pending_approval');
  });

  it('handles tool_result event', () => {
    const msgEl = createMsgEl();
    handleStreamEvent({
      type: 'tool_use', tool_id: 'tool_1', name: 'Bash', input: {},
    }, msgEl);

    handleStreamEvent({
      type: 'tool_result', tool_id: 'tool_1', output: '/tmp',
    }, msgEl);

    const block = msgEl.querySelector('[data-tool-id="tool_1"]');
    expect(block.querySelector('.tool-status').textContent).toBe('success');
  });

  it('handles tool_error event', () => {
    const msgEl = createMsgEl();
    handleStreamEvent({
      type: 'tool_use', tool_id: 'tool_1', name: 'Bash', input: {},
    }, msgEl);

    handleStreamEvent({
      type: 'tool_error', tool_id: 'tool_1', error: 'command failed',
    }, msgEl);

    const block = msgEl.querySelector('[data-tool-id="tool_1"]');
    expect(block.querySelector('.tool-status').textContent).toBe('error');
  });

  it('handles permission_request event', () => {
    const msgEl = createMsgEl();
    handleStreamEvent({
      type: 'permission_request',
      request_id: 'perm_1',
      tool: 'Bash',
      tool_input: {},
    }, msgEl);

    expect(state.awaitingApproval).toBe(true);
    expect(state.pendingPermissions.length).toBe(1);
    expect(msgEl.querySelector('.permission-card')).not.toBeNull();
  });

  it('handles result event with stats', () => {
    const msgEl = createMsgEl();
    handleStreamEvent({
      type: 'result',
      usage: { input_tokens: 100, output_tokens: 50 },
      duration_ms: 1500,
      cost_usd: 0.001,
      num_turns: 1,
    }, msgEl);

    const stats = msgEl.querySelector('.msg-stats');
    expect(stats).not.toBeNull();
    expect(stats.textContent).toContain('100');
    expect(stats.textContent).toContain('50');
    expect(document.getElementById('turn-tag').textContent).toBe('Turn 1');
  });

  it('handles error event', () => {
    const msgEl = createMsgEl();
    handleStreamEvent({ type: 'error', message: 'LLM failed' }, msgEl);

    const bodyEl = msgEl.querySelector('.msg-body');
    expect(bodyEl.innerHTML).toContain('LLM failed');
    expect(bodyEl.innerHTML).toContain('var(--err)');
  });

  it('handles done event', () => {
    const msgEl = createMsgEl();
    const contentEl = document.createElement('div');
    contentEl.className = 'msg-content streaming-active';
    msgEl.querySelector('.msg-body').appendChild(contentEl);

    const cursor = document.createElement('span');
    cursor.className = 'cursor-blink';
    contentEl.appendChild(cursor);

    handleStreamEvent({ type: 'done' }, msgEl);

    expect(contentEl.classList.contains('rendered')).toBe(true);
    expect(contentEl.classList.contains('streaming-active')).toBe(false);
    expect(msgEl.querySelector('.cursor-blink')).toBeNull();
  });

  it('handles system event', () => {
    const msgEl = createMsgEl();
    handleStreamEvent({ type: 'system', subtype: 'info' }, msgEl);

    const logsTab = document.querySelector('[data-rp-content="logs"]');
    expect(logsTab.querySelector('.log-line')).not.toBeNull();
  });
});
