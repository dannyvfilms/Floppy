import React from 'react';
import { mountRoot } from '../settings/root';
import { ListsPageView } from '../pages/ListsPageView';
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

// The release Lists hub keeps its server search/filter toolbar, htmx card grid
// and Alpine create/import modals. The shared view owns the heading, search,
// results and dialog order plus the empty/loading/error framing.
function ListsPageAdapter({ host, props }) {
  const slots = React.useMemo(() => collectPageSlots(host), [host]);
  return <ListsPageView
    palette={palette}
    heading={<PageSlot source={slots['lists-heading']} />}
    search={<PageSlot source={slots['lists-search']} />}
    content={<PageSlot source={slots['lists-content']} />}
    dialogs={<PageSlot source={slots['lists-dialogs']} />}
    footer={<PageSlot source={slots['lists-footer']} />}
    style={styles.root}
    testID={props?.testID || 'lists-page'} />;
}

const styles = { root: { display: 'block', position: 'static', gap: 0 } };

export function mountListsPage(host, props) {
  return mountRoot(host, <ListsPageAdapter host={host} props={props} />);
}
