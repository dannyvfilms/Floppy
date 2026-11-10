import { expectObject } from './payloadGuard.js';

const FILTER_KEYS = ['department', 'year', 'genre', 'implied_genre', 'source', 'rating', 'collection', 'sort', 'direction'];

// Only filters the user actually chose go on the wire, so the server's own
// defaults (newest first, titles ascending) stay in charge otherwise.
export function profileQuery(filters = {}) {
  const query = {};
  FILTER_KEYS.forEach(key => {
    const value = filters[key];
    if (value !== undefined && value !== null && value !== '' && value !== 'all') query[key] = value;
  });
  return query;
}

// Read-only profile contract shared by the native and browser adapters, served
// by the token-friendly API (`/api/v1/people`, `/api/v1/studios`).
export function createRemotePeopleActions(request) {
  return {
    mode: 'server',
    loadPerson({ source, personId, filters }) {
      return request(
        `/api/v1/people/${encodeURIComponent(source)}/${encodeURIComponent(personId)}/`,
        { query: profileQuery(filters) },
      ).then(data => expectObject(data, 'The profile'));
    },
    loadStudio({ source, studioId }) {
      return request(`/api/v1/studios/${encodeURIComponent(source)}/${encodeURIComponent(studioId)}/`)
        .then(data => expectObject(data, 'The profile'));
    },
  };
}

export function createLocalPeopleActions(reason) {
  const local = async () => { throw new Error(reason); };
  return {
    mode: 'local',
    reason,
    loadPerson: local,
    loadStudio: local,
  };
}
