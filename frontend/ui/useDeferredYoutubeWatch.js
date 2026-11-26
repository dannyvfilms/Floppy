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
    let retry;
    let timeout;
    let latest;
    async function load() {
      timeout = setTimeout(() => {
        setResponse({ path, request, watch: latest ?? unavailable });
        controller.abort();
      }, 30000);
      try {
        const result = await request(path, { query: { youtube_watch: 'only' }, signal: controller.signal });
        if (controller.signal.aborted) return;
        latest = detailYoutubeWatchModel(result.youtube_watch);
        if (result.youtube_watch_pending) {
          setResponse({ path, request, watch: latest?.seconds ? { ...latest, pending: true } : pending });
          retry = setTimeout(load, 5000);
        } else {
          setResponse({ path, request, watch: latest });
        }
      } catch {
        if (!controller.signal.aborted) setResponse({ path, request, watch: latest ?? unavailable });
      } finally {
        clearTimeout(timeout);
      }
    }
    load();
    return () => {
      clearTimeout(timeout);
      clearTimeout(retry);
      controller.abort();
    };
  }, [path, request]);
  if (!path) return null;
  if (!request) return unavailable;
  return response?.path === path && response.request === request ? response.watch : pending;
}
