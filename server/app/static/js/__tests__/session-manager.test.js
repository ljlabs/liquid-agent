import { describe, it, expect, vi, beforeEach } from 'vitest';
import { state } from '../state.js';
import { loadSessionList, switchToSession, createNewSession } from '../session-manager.js';

beforeEach(() => {
  vi.clearAllMocks();
  document.getElementById('conversation').innerHTML = '';
  document.getElementById('session-list').innerHTML = '';
  document.getElementById('endpoint-input').value = 'http://localhost:8787';
  state.activeSessionId = null;
  state.pendingPermissions = [];
});

describe('loadSessionList', () => {
  it('fetches and renders session list', async () => {
    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        sessions: [
          { id: 'sess_1', title: 'Session 1', updated_at: Date.now() / 1000 },
          { id: 'sess_2', title: 'Session 2', updated_at: Date.now() / 1000 - 3600 },
        ],
      }),
    });

    await loadSessionList();

    const list = document.getElementById('session-list');
    expect(list.children.length).toBe(2);
    expect(list.children[0].querySelector('.title').textContent).toBe('Session 1');
  });

  it('handles fetch error gracefully', async () => {
    globalThis.fetch.mockRejectedValue(new Error('network error'));
    await expect(loadSessionList()).resolves.toBeUndefined();
  });
});

describe('switchToSession', () => {
  it('updates state and UI for the new session', async () => {
    globalThis.fetch
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ rules: [] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ messages: [] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ permissions: [] }),
      });

    await switchToSession('sess_new', 'New Session', null);

    expect(state.activeSessionId).toBe('sess_new');
    expect(document.getElementById('session-id-tag').textContent).toBe('sess_new');
    expect(document.getElementById('session-title').textContent).toBe('New Session');
  });

  it('clears conversation before loading messages', async () => {
    document.getElementById('conversation').innerHTML = '<div class="msg">old</div>';

    globalThis.fetch
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ rules: [] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ messages: [] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ permissions: [] }),
      });

    await switchToSession('sess_1', 'Test', null);

    const conv = document.getElementById('conversation');
    expect(conv.querySelector('.msg')).toBeNull();
  });

  it('renders user messages from DB', async () => {
    globalThis.fetch
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ rules: [] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          messages: [{ id: 1, role: 'user', type: 'text', content: 'Hello', created_at: 1000 }],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ permissions: [] }),
      });

    await switchToSession('sess_1', 'Test', null);

    const conv = document.getElementById('conversation');
    expect(conv.querySelector('.msg.user')).not.toBeNull();
    expect(conv.querySelector('.msg-content').textContent).toContain('Hello');
  });

  it('renders thinking blocks from stored content', async () => {
    globalThis.fetch
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ rules: [] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          messages: [{
            id: 1, role: 'assistant', type: 'text',
            content: '<thought>analyzing</thought>Hello',
            created_at: 1000,
          }],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ permissions: [] }),
      });

    await switchToSession('sess_1', 'Test', null);

    const conv = document.getElementById('conversation');
    expect(conv.querySelector('.thinking-block')).not.toBeNull();
  });

  it('renders tool_use blocks', async () => {
    globalThis.fetch
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ rules: [] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          messages: [{
            id: 1, role: 'assistant', type: 'tool_use',
            tool_name: 'Bash', tool_id: 'tool_1',
            tool_input: '{"command":"pwd"}',
            created_at: 1000,
          }],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ permissions: [] }),
      });

    await switchToSession('sess_1', 'Test', null);

    const conv = document.getElementById('conversation');
    expect(conv.querySelector('[data-tool-id="tool_1"]')).not.toBeNull();
  });
});

describe('createNewSession', () => {
  it('creates session via POST and updates UI', async () => {
    globalThis.fetch
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ session_id: 'sess_new', model: 'mock-model' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ rules: [] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ sessions: [] }),
      });

    await createNewSession();

    expect(state.activeSessionId).toBe('sess_new');
    expect(document.getElementById('session-id-tag').textContent).toBe('sess_new');
    expect(document.getElementById('turn-tag').textContent).toBe('Turn 0');
  });
});
