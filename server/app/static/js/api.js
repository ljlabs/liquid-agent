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

export async function sendApprovalResponse(requestId, action) {
  try {
    await dbFetch('/v1/permissions/respond', {
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
