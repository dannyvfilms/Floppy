import React from 'react';
import { mountRoot } from '../settings/root';
import { LibraryPageView } from '../pages/LibraryPageView';
import { PageSlot, collectPageSlots } from './PageSlot.web';

const palette = {
  background: 'var(--color-page-bg)',
  surface: 'var(--color-surface)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceMuted: 'var(--color-surface-muted)',
  border: 'var(--color-surface-border)',
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  accent: 'var(--color-accent)',
  accentStrong: 'var(--color-accent)',
  accentText: 'var(--color-accent-contrast)',
  danger: 'var(--color-error-text)',
};

// The release library keeps its server heading, Alpine filter toolbar and htmx
// table/grid as the platform implementation. The shared view owns their order
// and the loading/empty/error framing, so no table, filter or column-menu
// behaviour is reimplemented in React.
function LibraryPageAdapter({ host, props }) {
  const slots = React.useMemo(() => collectPageSlots(host), [host]);
  return <LibraryPageView
    palette={palette}
    heading={<PageSlot source={slots['library-heading']} />}
    filterForm={<PageSlot source={slots['library-filter-form']} />}
    filters={<PageSlot source={slots['library-filters']} />}
    selection={<PageSlot source={slots['library-selection']} />}
    groupBanner={<PageSlot source={slots['library-group-banner']} />}
    content={<PageSlot source={slots['library-content']} />}
    bulkBar={<PageSlot source={slots['library-bulk-bar']} />}
    footer={<PageSlot source={slots['library-footer']} />}
    style={styles.root}
    testID={props?.testID || 'library-page'} />;
}

const styles = { root: { display: 'block', position: 'static', gap: 0 } };

export function mountLibraryPage(host, props) {
  return mountRoot(host, <LibraryPageAdapter host={host} props={props} />);
}
