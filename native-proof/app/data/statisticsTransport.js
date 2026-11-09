import { getActiveAuthSession } from './authSession.js';
import {
  createLocalStatisticsActions,
  createRemoteStatisticsActions,
  flattenStatisticsModel,
} from './statisticsTransportCore.js';

export { flattenStatisticsModel };

export function createStatisticsTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteStatisticsActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteStatisticsActions(auth.request);
  }
  return createLocalStatisticsActions(
    'Sign in to your Floppy server to load and save Statistics preferences.',
  );
}
