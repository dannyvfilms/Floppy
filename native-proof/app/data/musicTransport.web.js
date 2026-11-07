import { getActiveAuthSession } from './authSession.js';
import { createLocalMusicActions, createRemoteMusicActions } from './musicTransportCore.js';

const CSRF_COOKIE = 'csrftoken';

function readCsrfToken() {
  if (typeof document === 'undefined') return '';
  const row = document.cookie
    .split('; ')
    .find(cookie => cookie.startsWith(`${CSRF_COOKIE}=`));
  return row ? decodeURIComponent(row.slice(CSRF_COOKIE.length + 1)) : '';
}

function createRequest(baseUrl, csrfToken) {
  return async (path, options = {}) => {
    const isJson = options.json !== undefined;
    const response = await fetch(`${baseUrl}${path}`, {
      method: options.method || 'GET',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'X-CSRFToken': csrfToken,
        ...(isJson ? { 'Content-Type': 'application/json' } : {}),
      },
      body: isJson ? JSON.stringify(options.json) : undefined,
    });
    const data = response.status === 204
      ? null
      : await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(
        data?.detail
        || data?.error
        || `The server rejected the change (${response.status}).`,
      );
    }
    return data;
  };
}

// The same-origin Django session and CSRF cookie are the web transport. When
// they are absent (a static export or signed-out preview) the screen keeps its
// local demo state instead of pretending a write succeeded.
export function createMusicTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteMusicActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteMusicActions(auth.request);
  }
  const csrfToken = options.csrfToken || readCsrfToken();
  if (!csrfToken) {
    return createLocalMusicActions(
      'No signed-in same-origin session was found, so changes stay in the local preview.',
    );
  }
  const baseUrl = (options.baseUrl || '').replace(/\/$/, '');
  return createRemoteMusicActions(createRequest(baseUrl, csrfToken));
}
