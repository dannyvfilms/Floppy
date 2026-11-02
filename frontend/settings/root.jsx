import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';

export function mountRoot(host, element) {
  const fallback = [...host.childNodes].map((node) => node.cloneNode(true));
  const root = createRoot(host);
  try {
    flushSync(() => root.render(element));
  } catch (error) {
    root.unmount();
    host.replaceChildren(...fallback);
    throw error;
  }
  host.dataset.reactMounted = 'true';
  return () => {
    root.unmount();
    host.replaceChildren(...fallback);
    delete host.dataset.reactMounted;
  };
}
