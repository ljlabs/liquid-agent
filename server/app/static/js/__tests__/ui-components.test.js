import { describe, it, expect, vi, beforeEach } from 'vitest';
import { state } from '../state.js';
import {
  appendUserMessage,
  appendAssistantStub,
  appendOrUpdateThinking,
  appendToolBlock,
  updateToolBlock,
  appendPermissionCard,
  appendPlanningApprovalCard,
} from '../ui-components.js';

beforeEach(() => {
  document.getElementById('conversation').innerHTML = '';
});

describe('appendUserMessage', () => {
  it('creates user message with avatar and content', () => {
    appendUserMessage('Hello world');
    const conv = document.getElementById('conversation');
    const msg = conv.querySelector('.msg.user');
    expect(msg).not.toBeNull();
    expect(msg.querySelector('.avatar').textContent).toBe('U');
    expect(msg.querySelector('.role').textContent).toBe('You');
    expect(msg.querySelector('.msg-content').textContent).toBe('Hello world');
  });

  it('renders markdown content', () => {
    appendUserMessage('**bold** text');
    const conv = document.getElementById('conversation');
    expect(conv.querySelector('.msg-content').innerHTML).toContain('bold');
  });
});

describe('appendAssistantStub', () => {
  it('creates assistant message with cursor blink', () => {
    const el = appendAssistantStub();
    expect(el.classList.contains('assistant')).toBe(true);
    expect(el.querySelector('.avatar').textContent).toBe('A');
    expect(el.querySelector('.role').textContent).toBe('Claude');
    expect(el.querySelector('.cursor-blink')).not.toBeNull();
  });

  it('returns the created element', () => {
    const el = appendAssistantStub();
    expect(el).toBeInstanceOf(HTMLElement);
  });
});

describe('appendOrUpdateThinking', () => {
  it('creates thinking block on first call', () => {
    const msgEl = appendAssistantStub();
    appendOrUpdateThinking(msgEl, { data: 'thinking text', done: false });

    const block = msgEl.querySelector('.thinking-block');
    expect(block).not.toBeNull();
    expect(block.classList.contains('streaming')).toBe(true);
    expect(block.querySelector('.tbody').textContent).toBe('thinking text');
  });

  it('appends data on subsequent calls', () => {
    const msgEl = appendAssistantStub();
    appendOrUpdateThinking(msgEl, { data: 'part1', done: false });
    appendOrUpdateThinking(msgEl, { data: 'part2', done: false });

    const block = msgEl.querySelector('.thinking-block');
    expect(block.querySelector('.tbody').textContent).toBe('part1part2');
  });

  it('collapses block when done', () => {
    const msgEl = appendAssistantStub();
    appendOrUpdateThinking(msgEl, { data: 'thought', done: true });

    const block = msgEl.querySelector('.thinking-block');
    expect(block.classList.contains('collapsed')).toBe(true);
    expect(block.classList.contains('streaming')).toBe(false);
  });

  it('toggles collapsed on click', () => {
    const msgEl = appendAssistantStub();
    appendOrUpdateThinking(msgEl, { data: 'thought', done: true });

    const block = msgEl.querySelector('.thinking-block');
    block.click();
    expect(block.classList.contains('collapsed')).toBe(false);
    block.click();
    expect(block.classList.contains('collapsed')).toBe(true);
  });
});

describe('appendToolBlock', () => {
  it('creates tool block with correct attributes', () => {
    const bodyEl = document.createElement('div');
    const block = appendToolBlock(bodyEl, {
      id: 'tool_123',
      name: 'Bash',
      target: 'echo hello',
      status: 'running',
      input: { command: 'echo hello' },
    });

    expect(block.dataset.toolId).toBe('tool_123');
    expect(block.querySelector('.tool-name').textContent).toBe('Bash');
    expect(block.querySelector('.tool-target').textContent).toBe('echo hello');
    expect(block.querySelector('.tool-status').textContent).toBe('running');
    expect(block.querySelector('.tool-status').classList.contains('running')).toBe(true);
  });

  it('sets pending request id when provided', () => {
    const bodyEl = document.createElement('div');
    const block = appendToolBlock(bodyEl, {
      id: 'tool_1',
      name: 'Bash',
      target: '',
      status: 'pending_approval',
      input: {},
      pendingRequestId: 'perm_abc',
    });

    expect(block.dataset.pendingRequestId).toBe('perm_abc');
  });

  it('does not set pending request id when null', () => {
    const bodyEl = document.createElement('div');
    const block = appendToolBlock(bodyEl, {
      id: 'tool_1',
      name: 'Read',
      target: '/file.txt',
      status: 'success',
      input: { path: '/file.txt' },
      pendingRequestId: null,
    });

    expect(block.dataset.pendingRequestId).toBeUndefined();
  });

  it('displays JSON-formatted input', () => {
    const bodyEl = document.createElement('div');
    const block = appendToolBlock(bodyEl, {
      id: 'tool_1',
      name: 'Write',
      target: '/file.txt',
      status: 'running',
      input: { path: '/file.txt', content: 'hello' },
    });

    const pre = block.querySelector('.tool-body pre');
    expect(pre.textContent).toContain('path');
    expect(pre.textContent).toContain('/file.txt');
  });
});

describe('updateToolBlock', () => {
  it('updates status badge', () => {
    const bodyEl = document.createElement('div');
    const block = appendToolBlock(bodyEl, {
      id: 'tool_1', name: 'Bash', target: '', status: 'running', input: {},
    });

    updateToolBlock(block, { status: 'success' });
    expect(block.querySelector('.tool-status').textContent).toBe('success');
    expect(block.querySelector('.tool-status').classList.contains('success')).toBe(true);
  });

  it('adds output section with truncated text', () => {
    const bodyEl = document.createElement('div');
    const block = appendToolBlock(bodyEl, {
      id: 'tool_1', name: 'Bash', target: '', status: 'running', input: {},
    });

    const longOutput = 'x'.repeat(600);
    updateToolBlock(block, { status: 'success', output: longOutput });

    const section = block.querySelector('.tool-output-section');
    expect(section).not.toBeNull();
    expect(block.querySelector('.tool-output-pre').textContent.length).toBeLessThanOrEqual(500);
    expect(block.querySelector('.tool-output-expand')).not.toBeNull();
  });

  it('does not add expand button for short output', () => {
    const bodyEl = document.createElement('div');
    const block = appendToolBlock(bodyEl, {
      id: 'tool_1', name: 'Bash', target: '', status: 'running', input: {},
    });

    updateToolBlock(block, { status: 'success', output: 'short output' });
    expect(block.querySelector('.tool-output-expand')).toBeNull();
  });

  it('expands and collapses output on button click', () => {
    const bodyEl = document.createElement('div');
    const block = appendToolBlock(bodyEl, {
      id: 'tool_1', name: 'Bash', target: '', status: 'running', input: {},
    });

    const longOutput = 'x'.repeat(600);
    updateToolBlock(block, { status: 'success', output: longOutput });

    const btn = block.querySelector('.tool-output-expand');
    const pre = block.querySelector('.tool-output-pre');

    btn.click();
    expect(pre.textContent).toBe(longOutput);
    expect(btn.textContent).toBe('Collapse output');

    btn.click();
    expect(pre.textContent.length).toBeLessThanOrEqual(500);
    expect(btn.textContent).toContain('Show full output');
  });

  it('shows "Error" header for error status', () => {
    const bodyEl = document.createElement('div');
    const block = appendToolBlock(bodyEl, {
      id: 'tool_1', name: 'Bash', target: '', status: 'running', input: {},
    });

    updateToolBlock(block, { status: 'error', output: 'command failed' });
    const header = block.querySelector('.tool-output-header span');
    expect(header.textContent).toBe('Error');
  });

  it('shows "Output" header for success status', () => {
    const bodyEl = document.createElement('div');
    const block = appendToolBlock(bodyEl, {
      id: 'tool_1', name: 'Bash', target: '', status: 'running', input: {},
    });

    updateToolBlock(block, { status: 'success', output: 'ok' });
    const header = block.querySelector('.tool-output-header span');
    expect(header.textContent).toBe('Output');
  });

  it('does not add duplicate output sections', () => {
    const bodyEl = document.createElement('div');
    const block = appendToolBlock(bodyEl, {
      id: 'tool_1', name: 'Bash', target: '', status: 'running', input: {},
    });

    updateToolBlock(block, { status: 'success', output: 'first' });
    updateToolBlock(block, { status: 'success', output: 'second' });

    const sections = block.querySelectorAll('.tool-output-section');
    expect(sections.length).toBe(1);
  });
});

describe('appendPermissionCard', () => {
  it('creates permission card with tool name', () => {
    const bodyEl = document.createElement('div');
    appendPermissionCard(bodyEl, { request_id: 'req_1', tool: 'Bash', tool_input: {} });

    const card = bodyEl.querySelector('.permission-card');
    expect(card).not.toBeNull();
    expect(card.dataset.requestId).toBe('req_1');
    expect(card.textContent).toContain('Bash');
  });

  it('has three action buttons', () => {
    const bodyEl = document.createElement('div');
    appendPermissionCard(bodyEl, { request_id: 'req_1', tool: 'Bash', tool_input: {} });

    const card = bodyEl.querySelector('.permission-card');
    const buttons = card.querySelectorAll('.pbtn');
    expect(buttons.length).toBe(3);
    expect(buttons[0].dataset.action).toBe('allow');
    expect(buttons[1].dataset.action).toBe('allowAll');
    expect(buttons[2].dataset.action).toBe('deny');
  });

  it('disables buttons after click and shows result', async () => {
    globalThis.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ type: 'view' }) });

    const bodyEl = document.createElement('div');
    appendPermissionCard(bodyEl, { request_id: 'req_1', tool: 'Bash', tool_input: {} }, () => {});

    const card = bodyEl.querySelector('.permission-card');
    const allowBtn = card.querySelector('[data-action="allow"]');
    allowBtn.click();

    await new Promise(r => setTimeout(r, 50));
    expect(allowBtn.disabled).toBe(true);
    expect(card.querySelector('.pbtn.allow-all').disabled).toBe(true);
    expect(card.querySelector('.pbtn.deny').disabled).toBe(true);
  });
});

describe('appendPlanningApprovalCard', () => {
  it('creates planning card with plan content', () => {
    const bodyEl = document.createElement('div');
    appendPlanningApprovalCard(bodyEl, 'Step 1: analyze code');

    const card = bodyEl.querySelector('.planning-approval-card');
    expect(card).not.toBeNull();
    expect(card.textContent).toContain('Step 1: analyze code');
  });

  it('does not create duplicate cards', () => {
    const bodyEl = document.createElement('div');
    appendPlanningApprovalCard(bodyEl, 'plan 1');
    appendPlanningApprovalCard(bodyEl, 'plan 2');

    const cards = bodyEl.querySelectorAll('.planning-approval-card');
    expect(cards.length).toBe(1);
  });

  it('has proceed and revise buttons', () => {
    const bodyEl = document.createElement('div');
    appendPlanningApprovalCard(bodyEl, 'plan');

    const card = bodyEl.querySelector('.planning-approval-card');
    const buttons = card.querySelectorAll('.pbtn');
    expect(buttons.length).toBe(2);
    expect(buttons[0].dataset.action).toBe('proceed');
    expect(buttons[1].dataset.action).toBe('revise');
  });
});
