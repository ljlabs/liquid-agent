import { describe, it, expect } from 'vitest';
import { escapeHtml, formatTimeAgo, scrollToBottom, addLogLine } from '../utils.js';

describe('escapeHtml', () => {
  it('escapes ampersands', () => {
    expect(escapeHtml('a&b')).toBe('a&amp;b');
  });

  it('escapes angle brackets', () => {
    expect(escapeHtml('<script>')).toBe('&lt;script&gt;');
  });

  it('returns empty string for undefined', () => {
    expect(escapeHtml(undefined)).toBe('');
  });

  it('returns empty string for null', () => {
    expect(escapeHtml(null)).toBe('');
  });

  it('converts numbers to string', () => {
    expect(escapeHtml(42)).toBe('42');
  });

  it('handles mixed special characters', () => {
    expect(escapeHtml('<div>&</div>')).toBe('&lt;div&gt;&amp;&lt;/div&gt;');
  });

  it('returns plain text unchanged', () => {
    expect(escapeHtml('hello world')).toBe('hello world');
  });
});

describe('formatTimeAgo', () => {
  it('returns "now" for recent timestamps', () => {
    const now = Date.now() / 1000;
    expect(formatTimeAgo(now - 10)).toBe('now');
  });

  it('returns minutes for timestamps 1-59 minutes ago', () => {
    const now = Date.now() / 1000;
    expect(formatTimeAgo(now - 300)).toBe('5m');
  });

  it('returns hours for timestamps 1-23 hours ago', () => {
    const now = Date.now() / 1000;
    expect(formatTimeAgo(now - 7200)).toBe('2h');
  });

  it('returns days for timestamps > 24 hours ago', () => {
    const now = Date.now() / 1000;
    expect(formatTimeAgo(now - 172800)).toBe('2d');
  });

  it('handles falsy timestamp 0 by returning a large time string', () => {
    const result = formatTimeAgo(0);
    expect(result).toContain('d');
  });

  it('handles null timestamp', () => {
    const result = formatTimeAgo(null);
    expect(typeof result).toBe('string');
  });
});

describe('scrollToBottom', () => {
  it('scrolls conversation element to bottom', () => {
    const conv = document.getElementById('conversation');
    Object.defineProperty(conv, 'scrollHeight', { value: 1000, configurable: true });
    conv.scrollTop = 0;
    scrollToBottom();
    expect(conv.scrollTop).toBe(1000);
  });

  it('does not throw when conversation element missing', () => {
    const el = document.getElementById('conversation');
    el.id = 'temp';
    expect(() => scrollToBottom()).not.toThrow();
    el.id = 'conversation';
  });
});

describe('addLogLine', () => {
  it('appends a log line to the logs tab', () => {
    const logsTab = document.querySelector('[data-rp-content="logs"]');
    addLogLine('info', 'test message');
    const lines = logsTab.querySelectorAll('.log-line');
    expect(lines.length).toBe(1);
    expect(lines[0].classList.contains('info')).toBe(true);
    expect(lines[0].textContent).toContain('test message');
  });

  it('uses correct icon for error level', () => {
    const logsTab = document.querySelector('[data-rp-content="logs"]');
    addLogLine('error', 'error msg');
    const lines = logsTab.querySelectorAll('.log-line.error');
    expect(lines.length).toBe(1);
    expect(lines[0].querySelector('.lvl').textContent).toBe('✕');
  });

  it('uses correct icon for warn level', () => {
    const logsTab = document.querySelector('[data-rp-content="logs"]');
    addLogLine('warn', 'warn msg');
    const lines = logsTab.querySelectorAll('.log-line.warn');
    expect(lines.length).toBe(1);
    expect(lines[0].querySelector('.lvl').textContent).toBe('!');
  });

  it('escapes HTML in log text', () => {
    const logsTab = document.querySelector('[data-rp-content="logs"]');
    addLogLine('info', '<script>alert(1)</script>');
    const lines = logsTab.querySelectorAll('.log-line');
    const last = lines[lines.length - 1];
    expect(last.querySelector('span:last-child').textContent).toBe('<script>alert(1)</script>');
  });
});
