let activeSession = null;
const listeners = new Set();

export function setActiveAuthSession(session) {
  activeSession = session || null;
  listeners.forEach(listener => listener(activeSession));
}

export function getActiveAuthSession() {
  return activeSession;
}

export function subscribeAuthSession(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
