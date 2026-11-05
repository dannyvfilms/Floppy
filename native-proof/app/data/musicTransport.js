import { createLocalMusicActions, createRemoteMusicActions } from './musicTransportCore';

// Native credential storage, server selection and CSRF handling are still
// undesigned. A caller may inject a request function when that transport
// exists; until then the screen keeps its local preview state.
export function createMusicTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteMusicActions(options.request);
  }
  return createLocalMusicActions(
    'Native server login, server selection and CSRF transport are not configured yet.',
  );
}
