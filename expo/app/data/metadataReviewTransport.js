import { getActiveAuthSession } from './authSession.js';
import {
  createLocalMetadataReviewActions,
  createRemoteMetadataReviewActions,
} from './metadataReviewTransportCore.js';

export function createMetadataReviewTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteMetadataReviewActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteMetadataReviewActions(auth.request);
  }
  return createLocalMetadataReviewActions('Sign in to your Floppy server to review matches.');
}

export {
  candidatesFromPayload,
  previewFromPayload,
  queueFromPayload,
  unmappedRows,
} from './metadataReviewTransportCore.js';
