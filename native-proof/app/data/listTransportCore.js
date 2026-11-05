const listPath = listId => `/api/v1/lists/${encodeURIComponent(listId)}/`;
const listItemPath = (listId, itemId) => (
  `${listPath(listId)}items/${encodeURIComponent(itemId)}/`
);
const mediaPath = item => (
  `/api/v1/media/${encodeURIComponent(item.mediaType)}/`
  + `${encodeURIComponent(item.source)}/`
  + `${encodeURIComponent(item.mediaId)}/`
);

function collaboratorIds(members) {
  return members
    .filter(member => member.role !== 'owner')
    .map(member => member.id);
}

export function createRemoteListActions(request) {
  return {
    mode: 'server',
    updateVisibility({ listId, visibility }) {
      return request(listPath(listId), {
        method: 'PATCH',
        json: { is_public: visibility === 'public' },
      });
    },
    setCollaborators({ listId, members }) {
      return request(listPath(listId), {
        method: 'PATCH',
        json: { collaborators: collaboratorIds(members) },
      });
    },
    removeItem({ listId, itemId }) {
      return request(listItemPath(listId, itemId), { method: 'DELETE' });
    },
    rateItem({ item, score }) {
      return request(mediaPath(item), { method: 'PATCH', json: { score } });
    },
    bulkStatus({ itemIds, status }) {
      return request('/bulk/status', { method: 'POST', form: { status, item_ids: itemIds } });
    },
    bulkCollection({ itemIds }) {
      return request('/bulk/collection', { method: 'POST', form: { item_ids: itemIds } });
    },
  };
}

export function createLocalListActions(reason) {
  const local = async () => ({ local: true, reason });
  return {
    mode: 'local',
    reason,
    updateVisibility: local,
    setCollaborators: local,
    removeItem: local,
    rateItem: local,
    bulkStatus: local,
    bulkCollection: local,
  };
}
