import { vi } from 'vitest';

// Mock marked.parse globally
globalThis.marked = { parse: (text) => text };

// Mock document elements that are referenced before DOM is ready
document.body.innerHTML = `
<div id="conversation"></div>
<div id="session-list"></div>
<div id="session-title"></div>
<div id="session-id-tag"></div>
<div id="cwd-display"></div>
<div id="cwd-input"></div>
<div id="turn-tag"></div>
<div id="perm-mode-select">
  <option value="default">Default</option>
  <option value="acceptEdits">Accept edits</option>
  <option value="bypassPermissions">Bypass</option>
  <option value="plan">Plan</option>
</div>
<div id="model-select"><option value="mock-model">mock-model</option></div>
<div id="send-btn"></div>
<div id="prompt-input"></div>
<div id="char-count">0</div>
<div id="stream-status">idle</div>
<div id="endpoint-input"></div>
<div id="slash-menu"></div>
<div id="mode-pill"><svg></svg><span>Plan mode</span></div>
<div id="sidebar"></div>
<div id="mobile-toggle"></div>
<div id="new-session"></div>
<div id="tool-perm-list"></div>
<div id="max-turns"></div>
<div id="max-turns-val">25</div>
<div class="rp-tab active" data-rp-tab="files"></div>
<div class="rp-tab" data-rp-tab="usage"></div>
<div class="rp-tab" data-rp-tab="logs"></div>
<div class="rp-content active" data-rp-content="files"></div>
<div class="rp-content" data-rp-content="usage"></div>
<div class="rp-content" data-rp-content="logs"></div>
<div class="sidebar-section-header" data-toggle></div>
`;

// Mock localStorage
const localStorageMock = (() => {
  let store = {};
  return {
    getItem: vi.fn((key) => store[key] || null),
    setItem: vi.fn((key, value) => { store[key] = value; }),
    removeItem: vi.fn((key) => { delete store[key]; }),
    clear: vi.fn(() => { store = {}; }),
  };
})();
Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock });

// Mock EventSource
class MockEventSource {
  constructor(url) {
    this.url = url;
    this.onmessage = null;
    this.onerror = null;
    this.readyState = 1;
  }
  close() { this.readyState = 2; }
}
Object.defineProperty(globalThis, 'EventSource', {
  value: MockEventSource,
  writable: true,
  configurable: true,
});

// Mock fetch
globalThis.fetch = vi.fn();

// Set endpoint input value
document.getElementById('endpoint-input').value = 'http://localhost:8787';
