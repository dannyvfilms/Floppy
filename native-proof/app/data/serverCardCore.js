import { identityFromItem } from './detailTransportCore.js';

// Server presentation cards (Home shelves, search results) carry web URLs and
// modal actions but no item identity. The shared native action host writes
// through identities, so derive one from the card's detail URL and hand it to
// the Track and Lists actions. Cards that already have an identity, or that
// cannot be addressed (music rows, albums), pass through untouched.
export function enrichServerCard(card) {
  if (!card || typeof card !== 'object') return card;
  const identity = card.identity
    || (/\/details\/music\//.test(String(card.href || '')) ? null : identityFromItem(card));
  if (!identity) return card;
  const items = card.actions && Array.isArray(card.actions.items)
    ? card.actions.items.map(action => (
      action && action.modal && !action.media ? { ...action, media: identity } : action
    ))
    : null;
  return {
    ...card,
    identity: card.identity || { ...identity, title: card.title || '' },
    ...(items ? { actions: { ...card.actions, items } } : {}),
  };
}

// Link actions and title links on a card are web hrefs. Map the ones a native
// screen can open; everything else stays inert rather than navigating blind.
export function routeCardHref(href, navigate) {
  const path = String(href || '');
  if (!path || !navigate) return false;
  const [pathname, query = ''] = path.split(/[?#]/);
  const music = pathname.match(/\/details\/music\/artist\/(\d+)(?:\/[^/]+\/album\/(\d+))?/);
  if (music) {
    navigate('Music', {
      artistId: Number(music[1]),
      ...(music[2] ? { albumId: Number(music[2]) } : {}),
    });
    return true;
  }
  if (pathname.includes('/details/')) {
    navigate('Detail', { href: pathname });
    return true;
  }
  if (/\/history\/?$/.test(pathname)) {
    navigate('History', { filters: query });
    return true;
  }
  return false;
}

// Online music results link to the web create-from-search routes; the native
// app posts the provider id instead. Returns { kind, id } or null.
export function musicCreateFromHref(href) {
  const match = String(href || '').match(/\/music\/(artist|album)\/create\/([^/?#]+)/);
  return match ? { kind: match[1], id: decodeURIComponent(match[2]) } : null;
}
