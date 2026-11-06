import { getActiveAuthSession } from './authSession.js';
import {
  calendarModelFromPayload,
  createLocalCalendarActions,
  createRemoteCalendarActions,
} from './calendarTransportCore.js';

export function createCalendarTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteCalendarActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteCalendarActions(auth.request);
  }
  return createLocalCalendarActions('Sign in to Floppy to refresh calendar data on the server.');
}

export { calendarModelFromPayload, calendarQuery } from './calendarTransportCore.js';