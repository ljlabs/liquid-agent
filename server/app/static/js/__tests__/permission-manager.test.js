import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderToolPerms, loadToolDefaults, loadSessionToolRules } from '../permission-manager.js';

beforeEach(() => {
  vi.clearAllMocks();
  document.getElementById('tool-perm-list').innerHTML = '';
});

describe('renderToolPerms', () => {
  it('renders tool permission badges', () => {
    renderToolPerms([
      { tool: 'Bash', rule: 'ask' },
      { tool: 'Read', rule: 'allow' },
      { tool: 'Write', rule: 'deny' },
    ]);

    const list = document.getElementById('tool-perm-list');
    expect(list.children.length).toBe(3);
    expect(list.children[0].querySelector('.perm-badge').textContent).toBe('ask');
    expect(list.children[1].querySelector('.perm-badge').textContent).toBe('allow');
    expect(list.children[2].querySelector('.perm-badge').textContent).toBe('deny');
  });

  it('cycles badge on click: allow -> ask -> deny -> allow', () => {
    renderToolPerms([{ tool: 'Bash', rule: 'allow' }]);

    const badge = document.querySelector('.perm-badge');
    expect(badge.textContent).toBe('allow');
    expect(badge.classList.contains('allow')).toBe(true);

    badge.click();
    expect(badge.textContent).toBe('ask');
    expect(badge.classList.contains('ask')).toBe(true);

    badge.click();
    expect(badge.textContent).toBe('deny');
    expect(badge.classList.contains('deny')).toBe(true);

    badge.click();
    expect(badge.textContent).toBe('allow');
    expect(badge.classList.contains('allow')).toBe(true);
  });

  it('clears previous entries on re-render', () => {
    renderToolPerms([{ tool: 'Bash', rule: 'ask' }]);
    renderToolPerms([{ tool: 'Read', rule: 'allow' }]);

    const list = document.getElementById('tool-perm-list');
    expect(list.children.length).toBe(1);
    expect(list.children[0].querySelector('.name').textContent).toBe('Read');
  });
});

describe('loadToolDefaults', () => {
  it('fetches and renders tool defaults', async () => {
    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        tools: ['Bash', 'Read'],
        rules: [{ tool: 'Bash', rule: 'ask' }, { tool: 'Read', rule: 'allow' }],
      }),
    });

    await loadToolDefaults();

    const list = document.getElementById('tool-perm-list');
    expect(list.children.length).toBe(2);
  });
});

describe('loadSessionToolRules', () => {
  it('fetches and renders session-specific rules', async () => {
    document.getElementById('endpoint-input').value = 'http://localhost:8787';
    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        rules: [{ tool: 'Bash', rule: 'deny' }],
      }),
    });

    await loadSessionToolRules('sess_123');

    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://localhost:8787/v1/sessions/sess_123/tool-rules',
      expect.anything()
    );
    const list = document.getElementById('tool-perm-list');
    expect(list.children.length).toBe(1);
    expect(list.querySelector('.perm-badge').textContent).toBe('deny');
  });
});
