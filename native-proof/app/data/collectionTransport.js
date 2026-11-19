import { getActiveAuthSession } from './authSession.js';
import {
  collectionItemsFromPayload,
  createLocalCollectionActions,
  createRemoteCollectionActions,
} from './collectionTransportCore.js';

export function createCollectionTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteCollectionActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteCollectionActions(auth.request);
  }
  return createLocalCollectionActions(
    'Sign in to your Floppy server to load your collection.',
  );
}

export {
  ADD_COPY_UNAVAILABLE,
  COLLECTION_PAGE_SIZE,
  collectionAddressFor,
  collectionEntriesFromPayload,
  collectionItemsFromPayload,
  collectionQuery,
  copyFieldsFor,
  copyValuesFromCopy,
  customFieldGroupsFromPayload,
  customFilterFromGroups,
  customValuesPayload,
  emptyCopyValues,
  entryPayload,
  hasMoreFromPayload,
  mediaTypeColorsFromPayload,
  totalFromPayload,
} from './collectionTransportCore.js';
