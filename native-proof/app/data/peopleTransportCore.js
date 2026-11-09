const profileSlug = value => encodeURIComponent(value || 'profile');

const personPath = ({ source, personId, slug }) => (
  `/person/${encodeURIComponent(source)}/${encodeURIComponent(personId)}/`
  + `${profileSlug(slug)}?format=json`
);

const studioPath = ({ source, studioId, slug }) => (
  `/studio/${encodeURIComponent(source)}/${encodeURIComponent(studioId)}/`
  + `${profileSlug(slug)}?format=json`
);

// Read-only profile contract shared by the native and browser adapters. The
// Django person/studio views keep the HTML page and expose the same values as
// JSON only when the adapter asks for it.
export function createRemotePeopleActions(request) {
  return {
    mode: 'server',
    loadPerson({ source, personId, slug }) {
      return request(personPath({ source, personId, slug }));
    },
    loadStudio({ source, studioId, slug }) {
      return request(studioPath({ source, studioId, slug }));
    },
  };
}

export function createLocalPeopleActions(reason) {
  const local = async () => ({ local: true, reason });
  return {
    mode: 'local',
    reason,
    loadPerson: local,
    loadStudio: local,
  };
}
