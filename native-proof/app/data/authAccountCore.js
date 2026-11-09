import { AUTH_ERROR_CODES, AuthError } from './authTransportCore.js';

const NATIVE_HEADERS = { Accept: 'application/json', 'X-Floppy-Client': 'native' };
const ACCOUNT_PATH = '/settings/account/';

function requireAuth(auth) {
  return Boolean(auth && typeof auth.request === 'function');
}

export function createAccountTransport({ auth } = {}) {
  async function call(options = {}) {
    if (!requireAuth(auth)) {
      throw new AuthError('Sign in to your Floppy server first.', { code: AUTH_ERROR_CODES.SIGNED_OUT });
    }
    return auth.request(ACCOUNT_PATH, { ...options, headers: { ...NATIVE_HEADERS, ...(options.headers || {}) } });
  }

  async function load() {
    return call({ method: 'GET' });
  }

  async function updateProfile({ username } = {}) {
    return call({ method: 'POST', form: { username: String(username || '').trim() } });
  }

  async function changePassword({ oldPassword, newPassword1, newPassword2 } = {}) {
    return call({
      method: 'POST',
      form: {
        old_password: String(oldPassword || ''),
        new_password1: String(newPassword1 || ''),
        new_password2: String(newPassword2 || ''),
      },
    });
  }

  async function authenticator(action, { currentPassword = '', code = '' } = {}) {
    if (!['enable_authenticator', 'start_authenticator_setup', 'disable_authenticator'].includes(action)) {
      throw new AuthError('Unknown authenticator action.', { code: AUTH_ERROR_CODES.REQUEST_FAILED });
    }
    return call({
      method: 'POST',
      form: { action, current_password: String(currentPassword || ''), code: String(code || '').trim() },
    });
  }

  async function regenerateRecoveryCodes({ currentPassword = '' } = {}) {
    return call({
      method: 'POST',
      form: { action: 'regenerate_recovery_codes', current_password: String(currentPassword || '') },
    });
  }

  async function deleteAccount({ currentPassword, confirmUsername, confirmDelete = false } = {}) {
    const result = await call({
      method: 'POST',
      form: {
        action: 'delete_account',
        current_password: String(currentPassword || ''),
        confirm_username: String(confirmUsername || ''),
        confirm_delete: confirmDelete ? 'on' : '',
      },
    });
    if (auth && typeof auth.invalidate === 'function') {
      await auth.invalidate(AUTH_ERROR_CODES.SIGNED_OUT).catch(() => {});
    }
    return result;
  }

  return {
    mode: requireAuth(auth) ? 'server' : 'local',
    load,
    updateProfile,
    changePassword,
    enableAuthenticator: options => authenticator('enable_authenticator', options),
    startAuthenticatorSetup: options => authenticator('start_authenticator_setup', options),
    disableAuthenticator: options => authenticator('disable_authenticator', options),
    regenerateRecoveryCodes,
    deleteAccount,
  };
}
