import { secureStorage } from './authStorage';
import { createAccountTransport } from './authAccountCore';
import {
  AuthError,
  AUTH_ERROR_CODES,
  buildDeviceVerificationUrl,
  buildProviderLoginUrl,
  createAuthTransport,
  normalizeServerUrl,
  safeRedirectPath,
} from './authTransportCore';
import { setActiveAuthSession } from './authSession';

export const authTransport = createAuthTransport({
  storage: secureStorage,
  fetchImpl: (...args) => fetch(...args),
  onSessionChange: setActiveAuthSession,
});

export const accountTransport = createAccountTransport({ auth: authTransport });
export const restoreAuthSession = () => authTransport.restore();
export const signIn = options => authTransport.signIn(options);
export const signUp = options => authTransport.signUp(options);
export const recoverPassword = options => authTransport.recoverPassword(options);
export const signInWithToken = options => authTransport.signInWithToken(options);
export const startDeviceSignIn = options => authTransport.startDeviceSignIn(options);
export const pollDeviceSignIn = options => authTransport.pollDeviceSignIn(options);
export const isBrowserAuth = false;
// Native providers sign in through the device flow so the session returns to the app.
export const beginProviderSignIn = null;
export const signOut = () => authTransport.signOut();
export const testAuthConnection = options => authTransport.testConnection(options);
export const verifyAuthSession = () => authTransport.verify();
export const fetchAuthConfig = options => authTransport.fetchAuthConfig(options);
export const getAuthState = () => authTransport.getState();
export const getAuthorizedRequest = () => authTransport.getSession();
export const invalidateAuthSession = code => authTransport.invalidate(code || AUTH_ERROR_CODES.SIGNED_OUT);
export {
  AuthError,
  AUTH_ERROR_CODES,
  buildDeviceVerificationUrl,
  buildProviderLoginUrl,
  normalizeServerUrl,
  safeRedirectPath,
};

restoreAuthSession().catch(() => {});
