export const state = {
  activeSessionId: null,
  streaming: false,
  awaitingApproval: false,
  currentStreamAbortController: null,
  modeState: { current: 'default' },
  modeIdx: 0
};
