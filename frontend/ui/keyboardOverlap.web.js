import { useEffect, useState } from 'react';

// How far the on-screen keyboard covers the bottom of the page: the visual viewport
// shrinks when it opens, so the overlap is the layout height minus the viewport.
export function useKeyboardOverlap() {
  const [overlap, setOverlap] = useState(0);
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return undefined;
    const update = () => setOverlap(Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop));
    update();
    viewport.addEventListener('resize', update);
    return () => viewport.removeEventListener('resize', update);
  }, []);
  return overlap;
}
