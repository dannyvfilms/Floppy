import { getActiveAuthSession } from './authSession.js';
import {
  createLocalSettingsActions,
  createRemoteSettingsActions,
  notificationPatchFromForm,
  notificationsToForm,
  preferencesPatch,
  preferencesToForm,
} from './settingsTransportCore.js';

export function createSettingsTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteSettingsActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteSettingsActions(auth.request);
  }
  return createLocalSettingsActions(
    'Sign in to your Floppy server to load settings from the server.',
  );
}

export {
  notificationPatchFromForm,
  notificationsToForm,
  preferencesPatch,
  preferencesToForm,
};