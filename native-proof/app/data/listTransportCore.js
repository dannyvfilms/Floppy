const listPath = listId => `/api/v1/lists/${encodeURIComponent(listId)}/`;
const listItemPath = (listId, itemId) => (
  `${listPath(listId)}items/${encodeURIComponent(itemId)}/`
);
const smartRulesPath = listId => `/list/${encodeURIComponent(listId)}/smart-rules`;
const tierPath = (listId, action) => `/list/${encodeURIComponent(listId)}/tiers/${action}`;
const apiMediaPath = item => (
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
      return request(apiMediaPath(item), { method: 'PATCH', json: { score } });
    },
    saveSmartRules({ listId, rules }) {
      return request(smartRulesPath(listId), { method: 'POST', json: rules });
    },
    moveTierItem({ listId, itemId, tierId, itemIds = [] }) {
      return request(tierPath(listId, 'move'), {
        method: 'POST',
        form: { tier: tierId, item_id: itemId, 'item_ids[]': itemIds },
      });
    },
    saveTiers({ listId, tiers }) {
      return request(tierPath(listId, 'save'), { method: 'POST', json: { tiers } });
    },
    fillFromRatings({ listId }) {
      return request(tierPath(listId, 'fill'), { method: 'POST' });
    },
    undoTierFill({ listId, placements }) {
      return request(tierPath(listId, 'fill/undo'), { method: 'POST', json: { placements } });
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
    saveSmartRules: local,
    moveTierItem: local,
    saveTiers: local,
    fillFromRatings: local,
    undoTierFill: local,
    bulkStatus: local,
    bulkCollection: local,
  };
}
