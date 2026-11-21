import React, { useEffect, useMemo, useState } from 'react';
import { useWindowDimensions } from 'react-native';
import { mountRoot } from '../settings/root';
import { actionIcons } from './actionIcons';
import { CollectionGroup, CollectionRow, CollectionSectionHeading } from './CollectionCopies';
import { palette } from './mountCollectionCopyFields';
import { DetailGenres, DetailMetadata, DetailStudios, DetailWatchProviders } from './DetailSecondary';
import { detailSecondaryModel } from './detailSecondaryModel';

// The legacy CSS hides promoted facts and the genre card once the hero carousel shows them.
const CAROUSEL_ACTIVE = '.detail-carousel-grid:has(#detail-carousel-wrap:not(:empty))';
function carouselActive() {
  try { return !!document.querySelector(CAROUSEL_ACTIVE); } catch { return false; }
}

function useCarouselActive() {
  const [active, setActive] = useState(carouselActive);
  useEffect(() => {
    const wrap = document.getElementById('detail-carousel-wrap');
    if (!wrap) return undefined;
    const observer = new MutationObserver(() => setActive(carouselActive()));
    observer.observe(wrap, { childList: true });
    return () => observer.disconnect();
  }, []);
  return active;
}

function openLink(href) {
  if (/^https?:\/\//i.test(href) && new URL(href).origin !== window.location.origin) window.open(href, '_blank', 'noopener');
  else window.location.assign(href);
}

function Card({ props }) {
  const { width } = useWindowDimensions();
  const carousel = useCarouselActive();
  const model = useMemo(() => detailSecondaryModel(props.payload), [props.payload]);
  const titles = props.payload.titles || {};
  const wide = width >= 768;
  const promoted = carousel && width >= 600 && model.promoted?.length > 0;
  const common = { palette, variant: 'web', onOpenLink: openLink };
  switch (props.kind) {
    case 'heading':
      return <CollectionSectionHeading title={props.title} palette={palette} variant="web" />;
    case 'details': {
      const providers = model.watchProviderRegion !== 'UNSET' && Array.isArray(model.watchProviders)
        ? <DetailWatchProviders providers={model.watchProviders} region={model.watchProviderRegion}
          title={model.labels?.streaming} emptyLabel={model.labels?.noWatchProviders} palette={palette} variant="web" /> : null;
      return <DetailMetadata facts={model.facts} title={model.labels?.details} emptyLabel={model.labels?.noDetails}
        promoted={promoted} collectedPlatforms={props.payload.collected_platforms || []} platformCounts={model.platformCounts} {...common}>{wide ? providers : null}</DetailMetadata>;
    }
    case 'genres':
      // The genres move into the hero's tooltip when the carousel is active (wide, signed in).
      return carousel && wide && !model.publicView ? null : <DetailGenres genres={model.genres} title={titles.genres} {...common} />;
    case 'studios':
      return <DetailStudios studios={model.studios} title={titles.studios} {...common} />;
    case 'collection':
      return <CollectionGroup palette={palette} variant="web">
        {props.payload.collection_rows.map(row => <CollectionRow key={row.key} icon={row.key === 'seasons' ? actionIcons.fourSquare : actionIcons.list}
          label={row.label} value={row.value} palette={palette} />)}
      </CollectionGroup>;
    default:
      return null;
  }
}

// The Django wrapper's class hooks drive the legacy hiding rules, which the React card now owns.
const LEGACY_HOOKS = ['detail-sidebar-details', 'detail-sidebar-genres--in-tooltip'];

export function mountDetailSidebarCard(host, props) {
  const wrapper = host.parentElement;
  const hooks = LEGACY_HOOKS.filter(name => wrapper?.classList.contains(name));
  hooks.forEach(name => wrapper.classList.remove(name));
  // The replaced headings carried the gap between sidebar cards (mt-6).
  const spaced = ['genres', 'studios'].includes(props.kind);
  if (spaced) host.style.marginTop = '1.5rem';
  const dispose = mountRoot(host, <Card props={props} />);
  return () => { dispose(); hooks.forEach(name => wrapper.classList.add(name)); if (spaced) host.style.marginTop = ''; };
}
