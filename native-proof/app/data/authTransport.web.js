import {
  AuthError,
  AUTH_ERROR_CODES,
  buildDeviceVerificationUrl,
  buildProviderLoginUrl,
  createAuthTransport,
  normalizeServerUrl,
  safeRedirectPath,
} from './authTransportCore';
import { createAccountTransport } from './authAccountCore';
import { setActiveAuthSession } from './authSession';

// The Expo web export is served by Django under `<prefix>/static/native-proof/`.
// The credential is the same-origin session cookie set by the Floppy login, so
// nothing is stored here; the CSRF value is read from its cookie on each write.
const EXPORT_PATH = '/static/native-proof';
const CSRF_COOKIE = 'csrftoken';

function sitePrefix() {
  const path = window.location.pathname;
  const index = path.indexOf(EXPORT_PATH);
  return index > 0 ? path.slice(0, index).replace(/\/+$/, '') : '';
}

const browser = {
  serverUrl: () => `${window.location.origin}${sitePrefix()}`,
  readCsrfToken: () => {
    const row = document.cookie.split('; ').find(cookie => cookie.startsWith(`${CSRF_COOKIE}=`));
    return row ? decodeURIComponent(row.slice(CSRF_COOKIE.length + 1)) : '';
  },
};

const noStorage = {
  getItem: async () => null,
  setItem: async () => {},
  removeItem: async () => {},
};

const transport = createAuthTransport({
  storage: noStorage,
  fetchImpl: (...args) => fetch(...args),
  onSessionChange: setActiveAuthSession,
  browser,
});

// A social sign-in leaves the page: the provider and Floppy set the session
// cookie, then the server sends the browser back to this app.
function appPath() {
  return safeRedirectPath(`${window.location.pathname}${window.location.search}`, '/');
}

export const accountTransport = createAccountTransport({ auth: transport });
export const isBrowserAuth = true;
export const restoreAuthSession = () => transport.restore();
export const signIn = options => transport.signIn(options);
export const signUp = options => transport.signUp(options);
export const recoverPassword = options => transport.recoverPassword(options);
export const signInWithToken = options => transport.signInWithToken(options);
export const startDeviceSignIn = options => transport.startDeviceSignIn(options);
export const pollDeviceSignIn = options => transport.pollDeviceSignIn(options);
export const beginProviderSignIn = ({ provider }) => {
  const url = provider.loginUrl
    ? `${provider.loginUrl}${provider.loginUrl.includes('?') ? '&' : '?'}next=${encodeURIComponent(appPath())}`
    : buildProviderLoginUrl({ serverUrl: browser.serverUrl(), providerId: provider.id, redirectTo: appPath() });
  window.location.assign(url);
  return Promise.resolve();
};
export const signOut = () => transport.signOut();
export const testAuthConnection = options => transport.testConnection(options);
export const verifyAuthSession = () => transport.verify();
export const fetchAuthConfig = options => transport.fetchAuthConfig(options);
export const getAuthState = () => transport.getState();
export const getAuthorizedRequest = () => transport.getSession();
export const invalidateAuthSession = code => transport.invalidate(code || AUTH_ERROR_CODES.SIGNED_OUT);
export {
  AuthError,
  AUTH_ERROR_CODES,
  buildDeviceVerificationUrl,
  buildProviderLoginUrl,
  normalizeServerUrl,
  safeRedirectPath,
};
