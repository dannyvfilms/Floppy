import { useEffect, useState } from 'react';
import { SHELF_BREAKPOINTS, shelfCardWidth } from './HomeShelves';

// Browser side of the shelf card width Home and Search share: the phone card below 600px,
// widened to two across when the person's Mobile Grid preference is Comfortable.
// Release shelf cards are 11rem wide, dropping to the phone card size
// (--card-cap: 6.75rem) below 600px so a rail shows three cards, not two.
const PHONE_RAIL = window.matchMedia('(max-width: 600px)');

const mobileGridLayout = () => (document.body.dataset.mobileGrid === 'comfortable' ? 'comfortable' : 'compact');

const currentWidth = () => shelfCardWidth(
  PHONE_RAIL.matches ? window.innerWidth : SHELF_BREAKPOINTS.phone,
  mobileGridLayout(),
);

export function useShelfCardWidth() {
  const [width, setWidth] = useState(currentWidth);
  useEffect(() => {
    const update = () => setWidth(currentWidth());
    PHONE_RAIL.addEventListener('change', update);
    window.addEventListener('resize', update);
    const observer = new MutationObserver(update);
    observer.observe(document.body, { attributes: true, attributeFilter: ['data-mobile-grid'] });
    return () => {
      PHONE_RAIL.removeEventListener('change', update);
      window.removeEventListener('resize', update);
      observer.disconnect();
    };
  }, []);
  return width;
}
