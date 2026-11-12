import { getActiveAuthSession } from './authSession.js';
import {
  createLocalOnboardingActions,
  createRemoteOnboardingActions,
} from './onboardingTransportCore.js';

export function createOnboardingTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteOnboardingActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteOnboardingActions(auth.request);
  }
  return createLocalOnboardingActions('Sign in to your Floppy server to set it up.');
}

export { onboardingOffer, mediaTypeSelection, sourceSelection } from './onboardingTransportCore.js';
