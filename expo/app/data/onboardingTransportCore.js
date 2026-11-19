const ONBOARDING_PATH = '/api/v1/user/onboarding/';

// The server walks the first-run wizard (users.onboarding_views) and returns the
// current step with the data it needs; the client sends one action per step.
export function createRemoteOnboardingActions(request) {
  return {
    mode: 'server',
    load({ index = 0 } = {}) {
      return request(ONBOARDING_PATH, { query: index ? { index } : undefined });
    },
    act(action, payload = {}) {
      return request(ONBOARDING_PATH, { method: 'POST', body: { action, ...payload } });
    },
  };
}

export function createLocalOnboardingActions(reason) {
  const local = async () => ({ local: true, reason });
  return { mode: 'local', reason, load: local, act: local };
}

// Setup is offered while it is unfinished, like the web "Finish setting up"
// chip. It opens by itself only right after the person created the account.
export function onboardingOffer(state, { justSignedUp = false } = {}) {
  if (!state || state.local || state.demo || state.status === 'completed') {
    return { banner: false, open: false };
  }
  return { banner: state.status === 'in_progress', open: Boolean(justSignedUp) };
}

export function mediaTypeSelection(selected, value) {
  return selected.includes(value) ? selected.filter(item => item !== value) : [...selected, value];
}

export function sourceSelection(selected, slug) {
  return selected.includes(slug) ? selected.filter(item => item !== slug) : [...selected, slug];
}
