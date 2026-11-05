import { getActiveAuthSession } from './authSession.js';

function remoteCalendarActions(request) {
  return {
    mode: 'server',
    fetchReleases() {
      return request('/api/v1/calendar/update/', { method: 'POST' });
    },
    read() {
      return request('/api/v1/calendar/');
    },
  };
}

function localCalendarActions(reason) {
  return {
    mode: 'local',
    reason,
    fetchReleases: async () => ({ local: true, reason }),
    read: async () => ({ local: true, reason }),
  };
}

export function createCalendarTransport(options = {}) {
  if (typeof options.request === 'function') {
    return remoteCalendarActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return remoteCalendarActions(auth.request);
  }
  return localCalendarActions('Sign in to Floppy to refresh calendar data on the server.');
}
