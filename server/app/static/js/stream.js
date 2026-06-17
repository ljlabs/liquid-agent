/**
 * stream.js - Persistent single connection to backend.
 *
 * One SSE connection for the session lifetime.
 * All actions go through sendAction(); responses arrive on the stream.
 */

import { renderViewData } from './renderer.js';

let eventSource = null;
let reconnectTimeout = null;
let currentSessionId = null;
let streamActive = false;

const STORAGE_KEY = 'activeSessionId';

/**
 * Connect to the view stream. Single persistent connection.
 */
export function connectViewStream() {
    if (eventSource) {
        eventSource.close();
    }

    const endpoint = getEndpoint();
    const url = currentSessionId
        ? `${endpoint}/v1/view/stream?session_id=${currentSessionId}`
        : `${endpoint}/v1/view/stream`;

    eventSource = new EventSource(url);
    streamActive = true;

    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.type === 'done') {
            streamActive = false;
            return;
        }
        if (data.type === 'heartbeat') {
            return;
        }
        if (data.type === 'error') {
            console.error('[stream] error:', data.message);
            return;
        }

        // Update tracked session from ViewData
        if (data.active_session) {
            currentSessionId = data.active_session.id;
            localStorage.setItem(STORAGE_KEY, currentSessionId);
        }

        renderViewData(data);
    };

    eventSource.onerror = () => {
        console.error('[stream] connection error, reconnecting in 3s');
        streamActive = false;
        eventSource.close();
        eventSource = null;
        reconnectTimeout = setTimeout(connectViewStream, 3000);
    };
}

/**
 * Disconnect the stream.
 */
export function disconnectStream() {
    if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
        reconnectTimeout = null;
    }
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
    streamActive = false;
}

/**
 * Switch the stream to a different session.
 */
export function switchStream(sessionId) {
    currentSessionId = sessionId;
    if (sessionId) {
        localStorage.setItem(STORAGE_KEY, sessionId);
    } else {
        localStorage.removeItem(STORAGE_KEY);
    }
    disconnectStream();
    connectViewStream();
}

/**
 * Send an action to the backend via POST.
 * The response ViewData arrives on the SSE stream.
 */
export async function sendAction(action) {
    const endpoint = getEndpoint();
    try {
        const response = await fetch(`${endpoint}/v1/view`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(action),
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        // The initial ViewData snapshot comes back as JSON.
        // Render it immediately for fast UI response.
        const viewData = await response.json();
        if (viewData && viewData.type === 'view') {
            if (viewData.active_session) {
                currentSessionId = viewData.active_session.id;
                localStorage.setItem(STORAGE_KEY, currentSessionId);
            }
            renderViewData(viewData);
        }
    } catch (err) {
        console.error('[stream] sendAction failed:', err);
    }
}

/**
 * Get last active session from localStorage.
 */
export function getLastActiveSession() {
    return localStorage.getItem(STORAGE_KEY);
}

/**
 * Get current session ID.
 */
export function getCurrentSessionId() {
    return currentSessionId;
}

function getEndpoint() {
    const input = document.getElementById('endpoint-input');
    return input ? input.value.replace(/\/+$/, '') : 'http://localhost:8787';
}
