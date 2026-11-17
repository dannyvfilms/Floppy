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

// The person API sends credits a page at a time. A "more" request names one
// grid (section) and the page the last answer gave as watchedNextPage /
// filmographyNextPage; the server then fills only that grid.
const CREDIT_PAGES = {
  watched: { list: 'watched', next: 'watchedNextPage', total: 'watchedTotal', param: 'watched_page' },
  filmography: { list: 'filmography', next: 'filmographyNextPage', total: 'filmographyTotal', param: 'credits_page' },
};

export function creditPageQuery(page) {
  const spec = page && CREDIT_PAGES[page.section];
  if (!spec || !page.page) return {};
  return { section: page.section, [spec.param]: page.page };
}

// Add the next page of one grid to the profile on screen.
export function appendCreditPage(current, data, section) {
  const spec = CREDIT_PAGES[section];
  if (!current || !data || !spec) return current;
  const seen = new Set((current[spec.list] || []).map(entry => entry.id));
  const added = (data[spec.list] || []).filter(entry => !seen.has(entry.id));
  return {
    ...current,
    [spec.list]: [...(current[spec.list] || []), ...added],
    [spec.next]: data[spec.next] ?? null,
    [spec.total]: data[spec.total] ?? current[spec.total],
  };
}

// A background refresh (play totals) answers with the first page only. Keep
// the pages the viewer already loaded below it instead of shrinking the grid.
export function keepLoadedCredits(current, data) {
  if (!current || !data || current.kind !== 'person' || data.kind !== 'person') return data;
  const merged = { ...data };
  Object.values(CREDIT_PAGES).forEach(spec => {
    const shown = current[spec.list] || [];
    const fresh = data[spec.list] || [];
    if (shown.length > fresh.length) {
      const freshIds = new Set(fresh.map(entry => entry.id));
      merged[spec.list] = [...fresh, ...shown.slice(fresh.length).filter(entry => !freshIds.has(entry.id))];
      merged[spec.next] = current[spec.next] ?? null;
    }
  });
  return merged;
}

// Read-only profile contract shared by the native and browser adapters, served
// by the token-friendly API (`/api/v1/people`, `/api/v1/studios`).
export function createRemotePeopleActions(request) {
  return {
    mode: 'server',
    loadPerson({ source, personId, filters, page }) {
      return request(
        `/api/v1/people/${encodeURIComponent(source)}/${encodeURIComponent(personId)}/`,
        { query: { ...profileQuery(filters), ...creditPageQuery(page) } },
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
