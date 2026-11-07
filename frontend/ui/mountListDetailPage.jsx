import React from 'react';
import { mountRoot } from '../settings/root';
import { ListDetailPageView } from '../pages/ListDetailPageView';
import { PageSlot, collectPageSlots } from './PageSlot.web';

// The release list detail keeps its server header (counts, visibility chips,
// action menus), Alpine filter/search toolbar, htmx result grid/table/tier
// board and the create/edit modal. The shared view owns that section order and
// the empty/not-found framing.
function ListDetailPageAdapter({ host, props }) {
  const slots = React.useMemo(() => collectPageSlots(host), [host]);
  return <ListDetailPageView
    header={<PageSlot source={slots['list-detail-header']} />}
    controls={<PageSlot source={slots['list-detail-controls']} />}
    content={<PageSlot source={slots['list-detail-content']} />}
    dialogs={<PageSlot source={slots['list-detail-dialogs']} />}
    footer={<PageSlot source={slots['list-detail-footer']} />}
    style={styles.root}
    testID={props?.testID || 'list-detail-page'} />;
}

const styles = { root: { display: 'block', position: 'static', gap: 0 } };

export function mountListDetailPage(host, props) {
  return mountRoot(host, <ListDetailPageAdapter host={host} props={props} />);
}
