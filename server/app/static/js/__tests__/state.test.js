import { describe, it, expect } from 'vitest';
import { state } from '../state.js';

describe('state', () => {
  it('has default values', () => {
    expect(state.activeSessionId).toBeNull();
    expect(state.streaming).toBe(false);
    expect(state.awaitingApproval).toBe(false);
    expect(state.modeState.current).toBe('default');
  });

  it('is mutable', () => {
    state.activeSessionId = 'sess_123';
    state.streaming = true;
    state.awaitingApproval = true;
    state.modeState.current = 'plan';

    expect(state.activeSessionId).toBe('sess_123');
    expect(state.streaming).toBe(true);
    expect(state.awaitingApproval).toBe(true);
    expect(state.modeState.current).toBe('plan');

    // Reset
    state.activeSessionId = null;
    state.streaming = false;
    state.awaitingApproval = false;
    state.modeState.current = 'default';
  });
});
