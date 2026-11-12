import React, { useState } from 'react';
import { SettingsSidebarView } from '../../../frontend/pages/SettingsSidebarView';
import { actionIcons } from '../../../frontend/ui/actionIcons';
import { settingsNavIcons } from '../settingsNavIcons';
import SettingsLoadState from './SettingsLoadState';
import { useSettingsPalettes } from './settingsPalettes';
import { useSettingsResource } from './useSettingsResource';

export const surface = {
  id: 'SET-SIDEBAR',
  title: 'Sidebar',
  where: 'Settings, Sidebar (web: /settings/sidebar)',
  status: 'in_progress',
  note: 'Media-type visibility, order and the Discover switch load from and save to /api/v1/user/sidebar/, the same rules as the web form (order is kept for the hidden types too). Reordering uses up and down controls instead of dragging. Browser verified; device runtime not exercised.',
};

const chevron = d => ({
  viewBox: '0 0 24 24',
  root: { fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' },
  children: [{ tag: 'path', attrs: { d }, children: [] }],
});
const arrows = { up: chevron('m18 15-6-6-6 6'), down: chevron('m6 9 6 6 6-6') };

function SidebarForm({ transport, payload }) {
  const { settingsPalette, buttonPalette } = useSettingsPalettes();
  const [state, setState] = useState(() => ({
    order: payload.order || [],
    enabled: payload.media_types || {},
    showDiscover: payload.show_discover !== false,
  }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const change = patch => { setState(current => ({ ...current, ...patch })); setError(''); setSuccess(''); };

  const types = state.order.map(value => ({
    value, label: payload.labels?.[value] || value, icon: payload.icons?.[value], enabled: Boolean(state.enabled[value]),
  }));

  function move(value, step) {
    const index = state.order.indexOf(value);
    const target = index + step;
    if (index < 0 || target < 0 || target >= state.order.length) return;
    const order = [...state.order];
    order.splice(target, 0, order.splice(index, 1)[0]);
    change({ order });
  }

  async function save() {
    setSaving(true);
    try {
      await transport.saveSidebar({ enabled: state.enabled, order: state.order, showDiscover: state.showDiscover });
      setSuccess('Settings updated successfully.');
    } catch (cause) {
      setError(cause?.message || 'Sidebar settings could not be saved.');
    } finally {
      setSaving(false);
    }
  }

  return <SettingsSidebarView types={types} showDiscover={state.showDiscover} discoverIcon={payload.discover_icon}
    dragIcon={actionIcons.grip} labels={{ typesCopy: 'Control which media types are visible throughout the app (sidebar, search, calendar, notifications). Drag cards by their handles to set their sidebar order.' }}
    arrows={arrows} titleIcon={settingsNavIcons.sidebar} typesIcon={payload.discover_icon} saving={saving} error={error} success={success}
    onToggle={value => change({ enabled: { ...state.enabled, [value]: !state.enabled[value] } })}
    onMove={move} onToggleDiscover={value => change({ showDiscover: value })} onSave={save}
    palette={settingsPalette} buttonPalette={buttonPalette} />;
}

export default function SidebarSettingsSlot() {
  const resource = useSettingsResource(transport => transport.loadSidebar());
  if (resource.state !== 'ready') {
    return <SettingsLoadState state={resource.state} message={resource.message} onRetry={resource.reload} />;
  }
  return <SidebarForm transport={resource.transport} payload={resource.data} />;
}
