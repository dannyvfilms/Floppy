// The press-and-hold menu of a media card, built from what the card is given:
// its actions, whether it can be rated, and whether the status can be changed.
// Every consumer of the card gets the same menu in the same order, without
// writing one: Edit Lists, Edit Rating, Edit Status, Edit Tracking, a divider,
// then View History.

export const CARD_STATUSES = ['Planning', 'In progress', 'Paused', 'Completed', 'Dropped'];

const HISTORY = /\/history(?:[/?#]|$)/;

export function menuActionLabel(action) {
  if (action.modal === 'track') {
    if (action.media?.mediaType === 'episode') return action.title === 'Watched' ? 'Edit Watch' : 'Mark Watched';
    return 'Edit Tracking';
  }
  if (action.modal === 'lists') return 'Edit Lists';
  if (action.kind === 'link' && HISTORY.test(action.href || '')) return 'View History';
  if (action.vals?.action === 'planning') return 'Plan Title';
  if (action.vals?.action === 'dismiss') return 'Hide Title';
  return action.title;
}

const STATUS_TYPES = ['movie', 'tv', 'season', 'anime', 'manga', 'book', 'comic', 'comicissue', 'game', 'boardgame'];

export function buildCardMenu(model, { actions, canRate = false, canStatus = false } = {}) {
  const items = actions?.items || [];
  const entries = items.map((action, index) => ({
    id: `action-${index}`,
    title: menuActionLabel(action),
    attributes: { disabled: Boolean(action.disabled) },
    kind: action.modal === 'lists' ? 'lists' : action.modal === 'track' ? 'track'
      : action.kind === 'link' && HISTORY.test(action.href || '') ? 'history' : 'other',
  }));
  const pick = kind => entries.filter(entry => entry.kind === kind).map(({ kind: _kind, ...entry }) => entry);
  const statusAllowed = canStatus && model.identity && STATUS_TYPES.includes(model.identity.mediaType)
    && items.some(action => action.modal === 'track');
  const menu = [
    ...pick('other'),
    ...pick('lists'),
    ...(canRate ? [{ id: 'rating', title: 'Edit Rating' }] : []),
    ...(statusAllowed ? [{
      id: 'statuses',
      title: 'Edit Status',
      subactions: CARD_STATUSES.map(status => ({
        id: `status-${status}`, title: status, state: model.statusChip?.status === status ? 'on' : 'off',
      })),
    }] : []),
    ...pick('track'),
  ];
  const history = pick('history');
  if (history.length) menu.push(...(menu.length ? [{ id: 'divider', divider: true }] : []), ...history);
  return menu;
}
