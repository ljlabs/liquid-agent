import { describe, it, expect, vi, beforeEach } from 'vitest';
import { state } from '../state.js';

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  state.activeSessionId = null;
  state.streaming = false;
  document.getElementById('endpoint-input').value = 'http://localhost:8787';
});

describe('getLastActiveSession', () => {
  it('returns session ID from localStorage', async () => {
    localStorage.setItem('activeSessionId', 'sess_abc123');
    const { getLastActiveSession } = await import('../stream.js');
    expect(getLastActiveSession()).toBe('sess_abc123');
  });

  it('returns null when no session stored', async () => {
    const { getLastActiveSession } = await import('../stream.js');
    expect(getLastActiveSession()).toBeNull();
  });
});

describe('stream.js - sendAction', () => {
  it('POSTs action to /v1/view', async () => {
    vi.resetModules();
    const { sendAction } = await import('../stream.js');
    const viewData = { type: 'view', active_session: { id: 'sess_1' }, sessions: [], messages: [] };
    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(viewData),
    });

    await sendAction({ action: 'get_view' });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://localhost:8787/v1/view',
      expect.objectContaining({ method: 'POST' })
    );
  });

  it('updates activeSessionId from response', async () => {
    vi.resetModules();
    const { sendAction } = await import('../stream.js');
    const viewData = { type: 'view', active_session: { id: 'sess_1' }, sessions: [], messages: [] };
    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(viewData),
    });

    await sendAction({ action: 'get_view' });

    expect(localStorage.setItem).toHaveBeenCalledWith('activeSessionId', 'sess_1');
  });

  it('does not throw on HTTP error', async () => {
    vi.resetModules();
    const { sendAction } = await import('../stream.js');
    globalThis.fetch.mockResolvedValue({ ok: false, status: 500 });

    await expect(sendAction({ action: 'test' })).resolves.toBeUndefined();
  });

  it('sends interrupt action', async () => {
    vi.resetModules();
    const { sendAction } = await import('../stream.js');
    state.streaming = true;
    state.activeSessionId = 'sess_interrupt';
    globalThis.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ type: 'view' }) });

    await sendAction({ action: 'interrupt', session_id: 'sess_interrupt' });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://localhost:8787/v1/view',
      expect.objectContaining({
        body: JSON.stringify({ action: 'interrupt', session_id: 'sess_interrupt' }),
      })
    );
  });
});

describe('stream.js - connectViewStream', () => {
  it('creates EventSource with correct URL', async () => {
    vi.resetModules();
    const { connectViewStream } = await import('../stream.js');
    const originalES = globalThis.EventSource;
    let capturedUrl = null;
    globalThis.EventSource = class {
      constructor(url) { capturedUrl = url; this.onmessage = null; this.onerror = null; }
      close() {}
    };

    connectViewStream();
    expect(capturedUrl).toContain('/v1/view/stream');

    globalThis.EventSource = originalES;
  });
});

describe('stream.js - switchStream', () => {
  it('updates localStorage', async () => {
    vi.resetModules();
    const { switchStream } = await import('../stream.js');
    const originalES = globalThis.EventSource;
    globalThis.EventSource = class {
      constructor() { this.onmessage = null; this.onerror = null; }
      close() {}
    };

    switchStream('sess_new');
    expect(localStorage.setItem).toHaveBeenCalledWith('activeSessionId', 'sess_new');

    globalThis.EventSource = originalES;
  });

  it('removes from localStorage when switching to null', async () => {
    vi.resetModules();
    const { switchStream } = await import('../stream.js');
    const originalES = globalThis.EventSource;
    globalThis.EventSource = class {
      constructor() { this.onmessage = null; this.onerror = null; }
      close() {}
    };

    switchStream(null);
    expect(localStorage.removeItem).toHaveBeenCalledWith('activeSessionId');

    globalThis.EventSource = originalES;
  });
});
