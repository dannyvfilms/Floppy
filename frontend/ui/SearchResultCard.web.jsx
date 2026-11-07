import React, { useRef } from 'react';
import { MediaCard } from './MediaCard';

// Browser wrapper for a grid result. The release card renders one container div
// between `.media-card` and the visual so the `search-result-card` layout rules
// (square artwork, hover title) apply; the shared card owns everything inside it.
export function SearchResultCard({ model, labels, palette, actions, outline = true,
  onAction, onRate, renderRating, renderActionIcon }) {
  const mediaType = model.mediaType || '';
  const host = useRef(null);
  const shape = ['music', 'podcast'].includes(mediaType)
    ? 'search-result-card-square'
    : 'search-result-card';
  const video = mediaType === 'video' ? ' video-card video-card-landscape' : '';
  return <div
    ref={host}
    className={`media-card bg-[var(--color-surface)] rounded-lg overflow-hidden shadow-lg relative ${outline ? 'media-card-hover-outline transition-all' : ''} ${shape}${video} media-card-title-ellipsis media-card-title-bleed group`.replace(/\s+/g, ' ').trim()}
    style={{ '--card-title-rest-lines': 1, '--card-title-hover-lines': 3 }}
    data-media-type={mediaType}>
    <div>
      <MediaCard
        model={model}
        standalone={false}
        host={host}
        labels={labels}
        palette={palette}
        actions={actions}
        onAction={onAction}
        onRate={onRate}
        renderRating={renderRating}
        renderActionIcon={renderActionIcon}
      />
    </div>
  </div>;
}
