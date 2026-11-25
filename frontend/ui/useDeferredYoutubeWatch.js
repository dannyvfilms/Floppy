import { useEffect, useState } from 'react';
import { detailYoutubeWatchModel } from './detailSecondaryModel';

const pending = { pending: true };
const unavailable = {};

// Sharing the request lifecycle keeps browser navigation and native screen
// changes from applying an older game's answer.
export function useDeferredYoutubeWatch(path, request) {
  const [response, setResponse] = useState(null);
  useEffect(() => {
    if (!path || !request) return undefined;
    const controller = new AbortController();
    const timeout = setTimeout(() => {
      setResponse({ path, request, watch: unavailable });
      controller.abort();
    }, 30000);
    request(path, { query: { youtube_watch: 'only' }, signal: controller.signal })
      .then(result => {
        if (!controller.signal.aborted) {
          setResponse({ path, request, watch: detailYoutubeWatchModel(result.youtube_watch) });
        }
      }).catch(() => {
        if (!controller.signal.aborted) setResponse({ path, request, watch: unavailable });
      }).finally(() => clearTimeout(timeout));
    return () => {
      clearTimeout(timeout);
      controller.abort();
    };
  }, [path, request]);
  if (!path) return null;
  if (!request) return unavailable;
  return response?.path === path && response.request === request ? response.watch : pending;
}
