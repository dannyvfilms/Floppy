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

const noStorage = {
  getItem: async () => null,
  setItem: async () => {},
  removeItem: async () => {},
};

const transport = createAuthTransport({
  storage: noStorage,
  fetchImpl: (...args) => fetch(...args),
  onSessionChange: setActiveAuthSession,
});

function webAuthUnsupported() {
  throw new AuthError(
    'Sign in through the Floppy web login. Browser credentials stay in the same-origin session cookie.',
    { code: AUTH_ERROR_CODES.UNSUPPORTED },
  );
}

export const accountTransport = createAccountTransport({ auth: transport });
export const restoreAuthSession = () => transport.restore();
export const signIn = webAuthUnsupported;
export const signUp = webAuthUnsupported;
export const recoverPassword = webAuthUnsupported;
export const signInWithToken = webAuthUnsupported;
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
