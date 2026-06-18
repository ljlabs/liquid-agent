import { describe, it, expect, vi, beforeEach } from 'vitest';
import { dbFetch, sendApprovalResponse, fetchPendingPermissions } from '../api.js';

beforeEach(() => {
  vi.clearAllMocks();
  document.getElementById('endpoint-input').value = 'http://localhost:8787';
});

describe('dbFetch', () => {
  it('makes GET request to correct endpoint', async () => {
    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ data: 'test' }),
    });

    const result = await dbFetch('/v1/test');
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://localhost:8787/v1/test',
      expect.objectContaining({ headers: { 'Content-Type': 'application/json' } })
    );
    expect(result).toEqual({ data: 'test' });
  });

  it('throws on non-OK response', async () => {
    globalThis.fetch.mockResolvedValue({ ok: false, status: 500 });

    await expect(dbFetch('/v1/error')).rejects.toThrow('HTTP 500');
  });

  it('merges custom options', async () => {
    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    });

    await dbFetch('/v1/test', { method: 'POST', body: '{"key":"val"}' });
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://localhost:8787/v1/test',
      expect.objectContaining({ method: 'POST', body: '{"key":"val"}' })
    );
  });
});

describe('sendApprovalResponse', () => {
  it('sends approved=true for "allow" action', async () => {
    globalThis.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });

    await sendApprovalResponse('req_123', 'allow', 'sess_456');
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://localhost:8787/v1/sessions/sess_456/permissions/respond',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ request_id: 'req_123', approved: true, always: false }),
      })
    );
  });

  it('sends approved=true, always=true for "allowAll" action', async () => {
    globalThis.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });

    await sendApprovalResponse('req_123', 'allowAll', 'sess_456');
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://localhost:8787/v1/sessions/sess_456/permissions/respond',
      expect.objectContaining({
        body: JSON.stringify({ request_id: 'req_123', approved: true, always: true }),
      })
    );
  });

  it('sends approved=false for "deny" action', async () => {
    globalThis.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });

    await sendApprovalResponse('req_123', 'deny', 'sess_456');
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://localhost:8787/v1/sessions/sess_456/permissions/respond',
      expect.objectContaining({
        body: JSON.stringify({ request_id: 'req_123', approved: false, always: false }),
      })
    );
  });

  it('does not throw on network error', async () => {
    globalThis.fetch.mockRejectedValue(new Error('Network error'));
    await expect(sendApprovalResponse('req_123', 'allow', 'sess_456')).resolves.toBeUndefined();
  });
});

describe('fetchPendingPermissions', () => {
  it('returns permissions list', async () => {
    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ permissions: [{ request_id: 'req_1' }] }),
    });

    const result = await fetchPendingPermissions('sess_123');
    expect(result).toEqual([{ request_id: 'req_1' }]);
  });

  it('returns empty array when no permissions', async () => {
    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    });

    const result = await fetchPendingPermissions('sess_123');
    expect(result).toEqual([]);
  });

  it('returns empty array on error', async () => {
    globalThis.fetch.mockRejectedValue(new Error('fail'));
    const result = await fetchPendingPermissions('sess_123');
    expect(result).toEqual([]);
  });
});
