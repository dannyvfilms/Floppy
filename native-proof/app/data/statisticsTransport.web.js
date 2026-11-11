import {
  createLocalStatisticsActions,
  createRemoteStatisticsActions,
  featuredFromPerson,
  statisticsModelFromPayload,
  talentFromPayload,
} from './statisticsTransportCore';

export { featuredFromPerson, statisticsModelFromPayload, talentFromPayload };

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
    const form = options.form || {};
    const json = options.body !== undefined;
    const body = new URLSearchParams();
    Object.entries(form).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        body.set(key, value);
      }
    });
    const response = await fetch(`${baseUrl}${path}`, {
      method: options.method || 'GET',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'X-CSRFToken': csrfToken,
        ...(options.method && options.method !== 'GET'
          ? { 'Content-Type': json ? 'application/json' : 'application/x-www-form-urlencoded' }
          : {}),
      },
      body: options.method && options.method !== 'GET'
        ? (json ? JSON.stringify(options.body) : body.toString())
        : undefined,
    });
    const data = response.status === 204
      ? null
      : await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(
        data?.detail
        || data?.error
        || `The server rejected the request (${response.status}).`,
      );
    }
    return data;
  };
}

// The same-origin Django session and CSRF cookie are the web transport. When
// they are absent (a static export or signed-out preview) the screen shows a
// sign-in prompt instead of pretending a write succeeded.
export function createStatisticsTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteStatisticsActions(options.request);
  }
  const csrfToken = options.csrfToken || readCsrfToken();
  if (!csrfToken) {
    return createLocalStatisticsActions(
      'No signed-in same-origin session was found, so Statistics stays in the local preview.',
    );
  }
  const baseUrl = (options.baseUrl || '').replace(/\/$/, '');
  return createRemoteStatisticsActions(createRequest(baseUrl, csrfToken));
}
