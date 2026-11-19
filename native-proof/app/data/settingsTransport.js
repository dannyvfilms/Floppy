import { getActiveAuthSession } from './authSession.js';
import { createLocalSettingsActions, createRemoteSettingsActions } from './settingsTransportCore.js';

export function createSettingsTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteSettingsActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    const actions = createRemoteSettingsActions(auth.request, { authType: auth.getState?.()?.authType || auth.authType || 'token' });
    actions.serverUrl = auth.serverUrl || '';
    return actions;
  }
  return createLocalSettingsActions(
    'Sign in to your Floppy server to load settings from the server.',
  );
}

export {
  absoluteUrl,
  aboutFromPayload,
  advancedFromPayload,
  appearanceBody,
  appearanceFromPayload,
  applicationsFromPayload,
  cardsBody,
  cardsFromPayload,
  grantsFromPayload,
  historyFromPayload,
  homeBody,
  homeFromPayload,
  maskToken,
  notificationPatchFromForm,
  notificationsToForm,
  preferencesMeta,
  preferencesPatch,
  preferencesToForm,
  rssFeedUrl,
  rssFromPayload,
  scheduleBody,
  schedulesFromPayload,
  tokensFromPayload,
} from './settingsTransportCore.js';
