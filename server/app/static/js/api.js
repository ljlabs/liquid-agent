import { getEndpoint } from './utils.js';

export async function dbFetch(path, opts = {}) {
  const endpoint = getEndpoint();
  const res = await fetch(`${endpoint}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function sendApprovalResponse(requestId, action, sessionId) {
  try {
    await dbFetch(`/v1/sessions/${sessionId}/permissions/respond`, {
      method: 'POST',
      body: JSON.stringify({
        request_id: requestId,
        approved: action !== 'deny',
        always: action === 'allowAll'
      })
    });
  } catch (err) {
    console.error('Failed to send approval:', err);
  }
}

export async function fetchPendingPermissions(sessionId) {
  try {
    const data = await dbFetch(`/v1/sessions/${sessionId}/pending-permissions`);
    return data.permissions || [];
  } catch (err) {
    console.error('Failed to fetch pending permissions:', err);
    return [];
  }
}
