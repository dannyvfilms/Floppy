import { secureStorage } from './authStorage';
import { AuthError, AUTH_ERROR_CODES, createAuthTransport } from './authTransportCore';
import { setActiveAuthSession } from './authSession';

export const authTransport = createAuthTransport({
  storage: secureStorage,
  fetchImpl: (...args) => fetch(...args),
  onSessionChange: setActiveAuthSession,
});

export const restoreAuthSession = () => authTransport.restore();
export const signIn = options => authTransport.signIn(options);
export const signInWithToken = options => authTransport.signInWithToken(options);
export const signOut = () => authTransport.signOut();
export const testAuthConnection = options => authTransport.testConnection(options);
export const getAuthState = () => authTransport.getState();
export const getAuthorizedRequest = () => authTransport.getSession();
export const invalidateAuthSession = code => authTransport.invalidate(code || AUTH_ERROR_CODES.SIGNED_OUT);
export { AuthError, AUTH_ERROR_CODES };

restoreAuthSession().catch(() => {});
