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
    let latest;
    const timeout = setTimeout(() => {
      setResponse({ path, request, watch: latest ?? unavailable });
      controller.abort();
    }, 300000);
    async function load() {
      try {
        const result = await request(path, { query: { youtube_watch: 'only' }, signal: controller.signal });
        if (controller.signal.aborted) return;
        latest = detailYoutubeWatchModel(result.youtube_watch);
        if (result.youtube_watch_pending) {
          setResponse({ path, request, watch: latest?.seconds ? latest : pending });
          retry = setTimeout(load, 5000);
        } else {
          clearTimeout(timeout);
          setResponse({ path, request, watch: latest });
        }
      } catch {
        clearTimeout(timeout);
        if (!controller.signal.aborted) setResponse({ path, request, watch: latest ?? unavailable });
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
