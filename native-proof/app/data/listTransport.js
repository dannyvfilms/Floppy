import { createLocalListActions, createRemoteListActions } from './listTransportCore';

// Native credential storage, server selection and CSRF handling are still
// undesigned. A caller may inject a request function when that transport
// exists; until then the screen keeps its local preview state.
export function createListTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteListActions(options.request);
  }
  return createLocalListActions(
    'Native server login, server selection and CSRF transport are not configured yet.',
  );
}
