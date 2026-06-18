import { describe, it, expect, vi, beforeEach } from 'vitest';
import { state } from '../state.js';
import { renderViewData } from '../renderer.js';

beforeEach(() => {
  vi.clearAllMocks();
  document.getElementById('conversation').innerHTML = '';
  document.getElementById('session-list').innerHTML = '';
  document.getElementById('tool-perm-list').innerHTML = '';
  state.activeSessionId = null;
  state.streaming = false;
  state.modeState.current = 'default';
});

describe('renderViewData', () => {
  it('ignores null or non-view data', () => {
    renderViewData(null);
    renderViewData({ type: 'not-view' });
    renderViewData(undefined);
    expect(document.getElementById('conversation').innerHTML).toBe('');
  });

  it('renders session list', () => {
    renderViewData({
      type: 'view',
      sessions: [
        { id: 'sess_1', title: 'Test Session', updated_at: Date.now() / 1000, status: 'idle', message_count: 5 },
        { id: 'sess_2', title: 'Another Session', updated_at: Date.now() / 1000 - 3600, status: 'idle', message_count: 2 },
      ],
      active_session: null,
      messages: [],
      ui_state: {},
      pending_actions: [],
      tool_rules: [],
      files: { changed: [], recently_read: [] },
      usage: {},
      tool_call_log: [],
      session_log: [],
      available_models: [],
    });

    const list = document.getElementById('session-list');
    expect(list.children.length).toBe(2);
    expect(list.children[0].querySelector('.title').textContent).toBe('Test Session');
  });

  it('highlights active session in list', () => {
    state.activeSessionId = 'sess_1';
    renderViewData({
      type: 'view',
      sessions: [
        { id: 'sess_1', title: 'Active', updated_at: Date.now() / 1000, status: 'idle', message_count: 0 },
      ],
      active_session: null,
      messages: [],
      ui_state: {},
      pending_actions: [],
      tool_rules: [],
      files: { changed: [], recently_read: [] },
      usage: {},
      tool_call_log: [],
      session_log: [],
      available_models: [],
    });

    const list = document.getElementById('session-list');
    expect(list.children[0].classList.contains('active')).toBe(true);
  });

  it('renders active session metadata', () => {
    renderViewData({
      type: 'view',
      active_session: {
        id: 'sess_1',
        title: 'My Session',
        cwd: '/project',
        model: 'claude-sonnet-4-6',
        permission_mode: 'default',
        status: 'idle',
        turn_count: 5,
        created_at: 1000,
        updated_at: 2000,
      },
      sessions: [],
      messages: [],
      ui_state: {},
      pending_actions: [],
      tool_rules: [],
      files: { changed: [], recently_read: [] },
      usage: {},
      tool_call_log: [],
      session_log: [],
      available_models: [],
    });

    expect(document.getElementById('session-id-tag').textContent).toBe('sess_1');
    expect(document.getElementById('session-title').textContent).toBe('My Session');
    expect(document.getElementById('cwd-display').textContent).toBe('/project');
    expect(document.getElementById('turn-tag').textContent).toBe('Turn 5');
    expect(document.getElementById('perm-mode-select').value).toBe('default');
  });

  it('renders user messages', () => {
    renderViewData({
      type: 'view',
      active_session: { id: 's1', title: '', cwd: '', model: '', permission_mode: 'default', status: 'idle', turn_count: 0, created_at: 0, updated_at: 0 },
      sessions: [],
      messages: [{ id: 0, role: 'user', type: 'text', content: 'Hello', created_at: 1000 }],
      ui_state: {},
      pending_actions: [],
      tool_rules: [],
      files: { changed: [], recently_read: [] },
      usage: {},
      tool_call_log: [],
      session_log: [],
      available_models: [],
    });

    const conv = document.getElementById('conversation');
    expect(conv.querySelector('.msg.user')).not.toBeNull();
    expect(conv.querySelector('.msg.user .msg-content').textContent).toBe('Hello');
  });

  it('renders assistant messages with content blocks', () => {
    renderViewData({
      type: 'view',
      active_session: { id: 's1', title: '', cwd: '', model: '', permission_mode: 'default', status: 'idle', turn_count: 0, created_at: 0, updated_at: 0 },
      sessions: [],
      messages: [{
        id: 0,
        role: 'assistant',
        type: 'text',
        content: 'Hello',
        content_blocks: [
          { type: 'thinking', content: 'thinking text' },
          { type: 'text', content: 'Hello' },
        ],
        created_at: 1000,
      }],
      ui_state: {},
      pending_actions: [],
      tool_rules: [],
      files: { changed: [], recently_read: [] },
      usage: {},
      tool_call_log: [],
      session_log: [],
      available_models: [],
    });

    const conv = document.getElementById('conversation');
    const msg = conv.querySelector('.msg.assistant');
    expect(msg).not.toBeNull();
    expect(msg.querySelector('.thinking-block')).not.toBeNull();
    expect(msg.querySelector('.msg-content').textContent).toContain('Hello');
  });

  it('renders tool_use messages', () => {
    renderViewData({
      type: 'view',
      active_session: { id: 's1', title: '', cwd: '', model: '', permission_mode: 'default', status: 'idle', turn_count: 0, created_at: 0, updated_at: 0 },
      sessions: [],
      messages: [{
        id: 0,
        role: 'assistant',
        type: 'tool_use',
        content: '{"command":"pwd"}',
        tool_name: 'Bash',
        tool_id: 'tool_1',
        tool_input: { command: 'pwd' },
        status: 'success',
        created_at: 1000,
      }],
      ui_state: {},
      pending_actions: [],
      tool_rules: [],
      files: { changed: [], recently_read: [] },
      usage: {},
      tool_call_log: [],
      session_log: [],
      available_models: [],
    });

    const conv = document.getElementById('conversation');
    expect(conv.querySelector('[data-tool-id="tool_1"]')).not.toBeNull();
    expect(conv.querySelector('.tool-name').textContent).toBe('Bash');
  });

  it('renders UI state - streaming', () => {
    renderViewData({
      type: 'view',
      active_session: { id: 's1', title: '', cwd: '', model: '', permission_mode: 'default', status: 'idle', turn_count: 0, created_at: 0, updated_at: 0 },
      sessions: [],
      messages: [],
      ui_state: { streaming: true, awaiting_approval: false, mode: 'default', turn_tag: 'Turn 0' },
      pending_actions: [],
      tool_rules: [],
      files: { changed: [], recently_read: [] },
      usage: {},
      tool_call_log: [],
      session_log: [],
      available_models: [],
    });

    expect(state.streaming).toBe(true);
    expect(document.getElementById('send-btn').classList.contains('stop')).toBe(true);
    expect(document.getElementById('stream-status').textContent).toBe('streaming…');
  });

  it('renders UI state - awaiting approval', () => {
    renderViewData({
      type: 'view',
      active_session: { id: 's1', title: '', cwd: '', model: '', permission_mode: 'default', status: 'idle', turn_count: 0, created_at: 0, updated_at: 0 },
      sessions: [],
      messages: [],
      ui_state: { streaming: false, awaiting_approval: true, mode: 'default', turn_tag: 'Turn 0' },
      pending_actions: [],
      tool_rules: [],
      files: { changed: [], recently_read: [] },
      usage: {},
      tool_call_log: [],
      session_log: [],
      available_models: [],
    });

    expect(state.awaitingApproval).toBe(true);
    expect(document.getElementById('prompt-input').disabled).toBe(true);
    expect(document.getElementById('stream-status').textContent).toBe('awaiting approval…');
  });

  it('renders mode pill for plan mode', () => {
    renderViewData({
      type: 'view',
      active_session: { id: 's1', title: '', cwd: '', model: '', permission_mode: 'default', status: 'idle', turn_count: 0, created_at: 0, updated_at: 0 },
      sessions: [],
      messages: [],
      ui_state: { streaming: false, awaiting_approval: false, mode: 'plan', turn_tag: 'Turn 0' },
      pending_actions: [],
      tool_rules: [],
      files: { changed: [], recently_read: [] },
      usage: {},
      tool_call_log: [],
      session_log: [],
      available_models: [],
    });

    const modePill = document.getElementById('mode-pill');
    expect(modePill.classList.contains('active-plan')).toBe(true);
    expect(state.modeState.current).toBe('plan');
  });

  it('renders mode pill for acceptEdits', () => {
    renderViewData({
      type: 'view',
      active_session: { id: 's1', title: '', cwd: '', model: '', permission_mode: 'default', status: 'idle', turn_count: 0, created_at: 0, updated_at: 0 },
      sessions: [],
      messages: [],
      ui_state: { streaming: false, awaiting_approval: false, mode: 'acceptEdits', turn_tag: 'Turn 0' },
      pending_actions: [],
      tool_rules: [],
      files: { changed: [], recently_read: [] },
      usage: {},
      tool_call_log: [],
      session_log: [],
      available_models: [],
    });

    const modePill = document.getElementById('mode-pill');
    expect(modePill.classList.contains('active-accept')).toBe(true);
  });

  it('renders tool rules in sidebar', () => {
    renderViewData({
      type: 'view',
      active_session: { id: 's1', title: '', cwd: '', model: '', permission_mode: 'default', status: 'idle', turn_count: 0, created_at: 0, updated_at: 0 },
      sessions: [],
      messages: [],
      ui_state: {},
      pending_actions: [],
      tool_rules: [
        { tool: 'Bash', rule: 'ask' },
        { tool: 'Read', rule: 'allow' },
      ],
      files: { changed: [], recently_read: [] },
      usage: {},
      tool_call_log: [],
      session_log: [],
      available_models: [],
    });

    const list = document.getElementById('tool-perm-list');
    expect(list.children.length).toBe(2);
    expect(list.children[0].querySelector('.perm-badge').textContent).toBe('ask');
    expect(list.children[1].querySelector('.perm-badge').textContent).toBe('allow');
  });

  it('sets activeSessionId from viewData before rendering session list (Bug 1 fix)', () => {
    state.activeSessionId = 'sess_OLD';
    renderViewData({
      type: 'view',
      sessions: [
        { id: 'sess_OLD', title: 'Old Session', updated_at: Date.now() / 1000, status: 'idle', message_count: 0 },
        { id: 'sess_NEW', title: 'New Session', updated_at: Date.now() / 1000, status: 'idle', message_count: 0 },
      ],
      active_session: {
        id: 'sess_NEW',
        title: 'New Session',
        cwd: '/project',
        model: 'mock-model',
        permission_mode: 'default',
        status: 'idle',
        turn_count: 0,
        created_at: 0,
        updated_at: 0,
      },
      messages: [],
      ui_state: {},
      pending_actions: [],
      tool_rules: [],
      files: { changed: [], recently_read: [] },
      usage: {},
      tool_call_log: [],
      session_log: [],
      available_models: [],
    });

    expect(state.activeSessionId).toBe('sess_NEW');

    const list = document.getElementById('session-list');
    const activeItem = list.querySelector('.session-item.active');
    expect(activeItem).not.toBeNull();
    expect(activeItem.dataset.session).toBe('sess_NEW');
  });

  it('renders model dropdown', () => {
    renderViewData({
      type: 'view',
      active_session: { id: 's1', title: '', cwd: '', model: 'claude-sonnet-4-6', permission_mode: 'default', status: 'idle', turn_count: 0, created_at: 0, updated_at: 0 },
      sessions: [],
      messages: [],
      ui_state: {},
      pending_actions: [],
      tool_rules: [],
      files: { changed: [], recently_read: [] },
      usage: {},
      tool_call_log: [],
      session_log: [],
      available_models: ['claude-sonnet-4-6', 'gpt-4o'],
    });

    const select = document.getElementById('model-select');
    expect(select).not.toBeNull();
    expect(select.value).toBe('claude-sonnet-4-6');
  });
});
