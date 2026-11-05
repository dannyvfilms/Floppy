import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { ActionMenu, Button } from './controls';

// Alpine owns selection state and publishes it as `window.__bulkSelection`
// plus a `bulk-selection-change` event. This toolbar owns the actions: quick
// ones post from here, Update Status and Add Plays to History open the
// BulkActions dialogs (mountBulkActions.jsx), which keep working while you browse.
const read = () => window.__bulkSelection || { active: false, ids: [] };

const notify = (message, type = 'success') => {
  if (message && typeof window.showTrackToast === 'function') window.showTrackToast({ message, type });
};

function Toolbar({ config }) {
  const [selection, setSelection] = useState(read);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const change = () => setSelection(read());
    window.addEventListener('bulk-selection-change', change);
    change();
    return () => window.removeEventListener('bulk-selection-change', change);
  }, []);
  if (!selection.active) return null;

  const ids = selection.ids;
  const none = ids.length === 0;
  const open = detail => window.dispatchEvent(new CustomEvent('bulk-actions-open', { detail: { ...detail, itemIds: [...ids] } }));

  async function run(url, fields) {
    if (!ids.length || busy || !url) return;
    setBusy(true);
    try {
      const body = new URLSearchParams();
      ids.forEach(id => body.append('item_ids', id));
      Object.entries(fields).forEach(([key, value]) => body.append(key, value));
      const response = await fetch(url, { method: 'POST', headers: { 'X-CSRFToken': config.csrfToken }, body });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.success === false) throw new Error(data.error || 'The bulk action failed.');
      notify(data.message || 'Bulk action completed.');
      window.dispatchEvent(new CustomEvent('bulk-actions-done'));
    } catch (error) {
      notify(error.message || 'The bulk action failed.', 'error');
    } finally {
      setBusy(false);
    }
  }

  const locked = none || busy;
  return <div className="ui-bulk-bar" role="toolbar" aria-label="Bulk actions">
    <div className="ui-bulk-count">
      <span><strong>{ids.length.toLocaleString()}</strong> selected</span>
      <button type="button" onClick={() => window.dispatchEvent(new CustomEvent('bulk-actions-clear'))}>Clear</button>
      {none && <span className="ui-bulk-hint" role="status">Pick items to use these actions.</span>}
    </div>
    <div className="ui-bulk-groups">
      <div className="ui-bulk-group" role="group" aria-label="Library">
        <span className="ui-bulk-group-label">Library</span>
        <div className="ui-bulk-buttons">
          <ActionMenu label="Update Status" disabled={locked}
            items={[{ heading: 'Changes status only. Completed on a show also adds plays dated today.' },
              ...config.statuses.map(status => ({ label: status.label, onSelect: () => open({ kind: 'status', status: status.value, statusLabel: status.label }) }))]} />
          <ActionMenu label="Add to List" disabled={locked} empty="No editable lists."
            items={config.lists.map(list => ({ label: list.label, onSelect: () => run(config.listUrl, { custom_list_id: list.id }) }))} />
          <Button type="button" secondary disabled={locked} onClick={() => run(config.collectionUrl, {})}>Add to Collection</Button>
          <ActionMenu label="Apply Tag" disabled={locked} empty="No tags yet."
            items={config.tags.map(tag => ({ label: tag, actions: [
              { label: 'Add', onSelect: () => run(config.tagUrl, { tag_name: tag, action: 'add' }) },
              { label: 'Remove', onSelect: () => run(config.tagUrl, { tag_name: tag, action: 'remove' }) }] }))} />
        </div>
      </div>
      <div className="ui-bulk-group" role="group" aria-label="History">
        <span className="ui-bulk-group-label">History</span>
        <div className="ui-bulk-buttons">
          <Button type="button" disabled={locked} title="For TV shows and anime. Counts in Statistics and streaks."
            onClick={() => open({ kind: 'plays' })}>Add Plays to History</Button>
        </div>
      </div>
    </div>
  </div>;
}

export function mountBulkToolbar(host, props) {
  return mountRoot(host, <Toolbar config={props} />);
}
