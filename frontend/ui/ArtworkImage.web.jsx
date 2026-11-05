import React, { useEffect, useState } from 'react';
import { StyleSheet } from 'react-native';

const DEFAULT_PALETTE = {
  placeholder: '#3f3f46',
  textMuted: '#a1a1aa',
  staleBackground: 'rgba(245, 158, 11, 0.15)',
  staleBorder: 'rgba(245, 158, 11, 0.3)',
  staleText: '#fde68a',
};

const DEFAULT_LABELS = {
  loading: 'Loading artwork',
  unavailable: 'Artwork unavailable',
  stale: 'Artwork may be out of date',
};

const VIDEO_FALLBACK_WIDTH = 120;

function artworkSources(src, fallback) {
  return [src, fallback].filter(Boolean);
}

function rootStyle(style) {
  return {
    position: 'relative',
    overflow: 'hidden',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    ...(StyleSheet.flatten(style) || {}),
  };
}

/** Browser artwork presentation: the same fallback chain and state contract as
 * the native component, as a real image that artwork-loading.js can promote
 * and image-fallback.js can catch for server fallbacks.
 */
export function ArtworkImage({
  src,
  fallback,
  title,
  source = 'primary',
  variant = 'media-card',
  loading = 'lazy',
  decoding = 'sync',
  fallbackOnSmall = false,
  stale = false,
  style,
  resizeMode = 'cover',
  palette = {},
  labels = {},
  children,
}) {
  const colors = { ...DEFAULT_PALETTE, ...palette };
  const copy = { ...DEFAULT_LABELS, ...labels };
  const sources = artworkSources(src, fallback);
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState(sources.length ? 'loading' : 'unavailable');

  useEffect(() => {
    setAttempt(0);
    setStatus(sources.length ? 'loading' : 'unavailable');
  }, [src, fallback]);

  const uri = sources[attempt] || null;

  function handleLoad(event) {
    const width = event.currentTarget?.naturalWidth;
    if (fallbackOnSmall && attempt === 0 && sources.length > 1 && width === VIDEO_FALLBACK_WIDTH) {
      setAttempt(1);
      setStatus('loading');
      return;
    }
    setStatus('loaded');
  }

  function handleError() {
    if (attempt + 1 < sources.length) {
      setAttempt(attempt + 1);
      setStatus('loading');
      return;
    }
    setStatus('unavailable');
  }

  const placeholder = status === 'loaded'
    ? null
    : title || (status === 'unavailable' ? copy.unavailable : copy.loading);

  return <span style={{ ...rootStyle(style), backgroundColor: colors.placeholder }}>
    {uri && status !== 'unavailable' ? <img src={uri} alt={title || ''} loading={loading} decoding={decoding}
      className={variant === 'media-card' ? 'media-card-poster' : undefined}
      data-media-artwork="" data-image-source={source} data-artwork-state={status}
      data-image-fallback={fallback || undefined}
      data-image-fallback-on-small={fallbackOnSmall ? 'true' : undefined}
      data-image-fallback-applied={status === 'unavailable' ? 'true' : undefined}
      style={{
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        left: 0,
        width: '100%',
        height: '100%',
        objectFit: resizeMode === 'contain' ? 'contain' : 'cover',
      }}
      onLoad={handleLoad} onError={handleError} /> : null}
    {placeholder ? <span aria-live="polite"
      style={{ paddingLeft: 8, paddingRight: 8, textAlign: 'center', fontSize: 11, fontWeight: 600, color: colors.textMuted }}>
      {placeholder}
    </span> : null}
    {stale ? <span style={{
      position: 'absolute', left: 6, bottom: 6, borderWidth: 1, borderRadius: 4,
      paddingLeft: 4, paddingRight: 4, paddingTop: 2, paddingBottom: 2,
      backgroundColor: colors.staleBackground, borderColor: colors.staleBorder,
      color: colors.staleText, fontSize: 9, fontWeight: 600,
    }}>{copy.stale}</span> : null}
    {children}
  </span>;
}
