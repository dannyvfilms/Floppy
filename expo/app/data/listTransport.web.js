import { getActiveAuthSession } from './authSession.js';
import { createLocalListActions, createRemoteListActions } from './listTransportCore';

const CSRF_COOKIE = 'csrftoken';

function readCsrfToken() {
  if (typeof document === 'undefined') {
    return '';
  }
  const row = document.cookie
    .split('; ')
    .find(cookie => cookie.startsWith(`${CSRF_COOKIE}=`));
  return row ? decodeURIComponent(row.slice(CSRF_COOKIE.length + 1)) : '';
}

function buildBody({ json, form }) {
  if (json !== undefined) {
    return {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(json),
    };
  }
  if (form !== undefined) {
    const body = new URLSearchParams();
    Object.entries(form).forEach(([key, value]) => {
      if (Array.isArray(value)) {
        value.forEach(entry => body.append(key, entry));
      } else if (value !== undefined && value !== null) {
        body.append(key, value);
      }
    });
    return {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    };
  }
  return { headers: {}, body: undefined };
}

function createRequest(baseUrl, csrfToken) {
  return async (path, options = {}) => {
    const { headers, body } = buildBody(options);
    const query = Object.entries(options.query || {})
      .filter(([, value]) => value !== undefined && value !== null && value !== '')
      .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
      .join('&');
    const response = await fetch(`${baseUrl}${path}${query ? `?${query}` : ''}`, {
      method: options.method || 'GET',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'X-CSRFToken': csrfToken,
        ...headers,
      },
      body,
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
// they are absent (a static export or signed-out preview) the screen falls back
// to a local transport instead of pretending a write succeeded.
export function createListTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteListActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteListActions(auth.request);
  }
  const csrfToken = options.csrfToken || readCsrfToken();
  if (!csrfToken) {
    return createLocalListActions(
      'No signed-in same-origin session was found, so changes stay in the local preview.',
    );
  }
  const baseUrl = (options.baseUrl || '').replace(/\/$/, '');
  return createRemoteListActions(createRequest(baseUrl, csrfToken));
}
