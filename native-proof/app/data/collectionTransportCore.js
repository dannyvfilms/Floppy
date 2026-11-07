const COLLECTION_LIMIT = 100;

function dateValue(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toISOString().slice(0, 10);
}

function itemKey(entry) {
  const item = entry.item || {};
  return `${item.media_type}-${item.source}-${item.media_id}`;
}

export function collectionItemsFromPayload(payload) {
  const entries = Array.isArray(payload) ? payload : payload?.results || [];
  const grouped = new Map();
  entries.forEach(entry => {
    const key = itemKey(entry);
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(entry);
  });
  return [...grouped.entries()].map(([key, copies]) => {
    const first = copies[0];
    const item = first.item || {};
    const mediaType = item.library_media_type || item.media_type || '';
    return {
      id: String(first.id),
      mediaType,
      title: item.title || '',
      identity: {
        mediaType,
        source: item.source,
        mediaId: item.media_id,
      },
      image: { src: item.image || null, fallback: '' },
      format: first.media_type || '',
      resolution: first.resolution || '',
      hdr: first.hdr || '',
      location: '',
      rating: null,
      collectedAt: dateValue(first.collected_at),
      releaseDate: dateValue(item.release_datetime),
      lastWatched: '',
      copyLabel: '',
      customValues: {},
      copies: copies.map(copy => ({
        id: String(copy.id),
        label: copy.media_type || 'Copy',
        mediaType: copy.media_type || '',
        resolution: copy.resolution || '',
        hdr: copy.hdr || '',
        audioCodec: copy.audio_codec || '',
        audioChannels: copy.audio_channels || '',
        bitrate: copy.bitrate == null ? '' : String(copy.bitrate),
        is3d: Boolean(copy.is_3d),
        purchasePrice: '',
        purchaseLocation: '',
        collectedAt: dateValue(copy.collected_at),
      })),
      entryKey: key,
    };
  });
}

export function collectionQuery({ limit = COLLECTION_LIMIT, offset = 0 } = {}) {
  return { limit, offset, ordering: '-collected_at' };
}

export function createRemoteCollectionActions(request) {
  return {
    mode: 'server',
    load({ limit = COLLECTION_LIMIT, offset = 0 } = {}) {
      return request('/api/v1/collection/', { query: collectionQuery({ limit, offset }) });
    },
  };
}

export function createLocalCollectionActions(reason) {
  return {
    mode: 'local',
    reason,
    load: async () => ({ local: true, reason }),
  };
}