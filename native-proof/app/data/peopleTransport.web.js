import { getActiveAuthSession } from './authSession.js';
import { createLocalPeopleActions, createRemotePeopleActions } from './peopleTransportCore';

const CSRF_COOKIE = 'csrftoken';

function readCsrfToken() {
  if (typeof document === 'undefined') return '';
  const row = document.cookie
    .split('; ')
    .find(cookie => cookie.startsWith(`${CSRF_COOKIE}=`));
  return row ? decodeURIComponent(row.slice(CSRF_COOKIE.length + 1)) : '';
}

function createRequest(baseUrl, csrfToken) {
  return async (path) => {
    const response = await fetch(`${baseUrl}${path}`, {
      method: 'GET',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'X-CSRFToken': csrfToken,
      },
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(
        data?.detail
        || data?.error
        || `The server rejected the profile request (${response.status}).`,
      );
    }
    return data;
  };
}

// The same-origin Django session is the web transport. A static export or
// signed-out preview keeps the local demo profile instead of inventing data.
export function createPeopleTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemotePeopleActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemotePeopleActions(auth.request);
  }
  const csrfToken = options.csrfToken || readCsrfToken();
  if (!csrfToken) {
    return createLocalPeopleActions(
      'No signed-in same-origin session was found, so profiles stay in the local preview.',
    );
  }
  const baseUrl = (options.baseUrl || '').replace(/\/$/, '');
  return createRemotePeopleActions(createRequest(baseUrl, csrfToken));
}
