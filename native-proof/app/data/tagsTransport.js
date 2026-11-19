import { getActiveAuthSession } from './authSession.js';
import {
  createLocalTagsActions,
  createRemoteTagsActions,
} from './tagsTransportCore.js';

export function createTagsTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteTagsActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteTagsActions(auth.request);
  }
  return createLocalTagsActions(
    'Sign in to your Floppy server to load your tags.',
  );
}

export { sortTags, tagFromPayload, tagsFromPayload } from './tagsTransportCore.js';
