import React, { useEffect, useRef, useState } from 'react';
import { Text } from 'react-native';
import { SettingsActivityView } from '../../../frontend/pages/SettingsActivityView';
import { ProviderActivityView } from '../../../frontend/providers/ProviderActivityView';
import { ConfirmDialog } from '../../../frontend/settings/ConfirmDialog';
import { absoluteUrl } from '../data/settingsTransport';
import { copyText } from '../data/fileFlows';
import { palette } from '../theme';
import { actionIcons } from '../../../frontend/ui/actionIcons';
import { settingsNavIcons } from '../settingsNavIcons';
import SettingsLoadState from './SettingsLoadState';
import { useSettingsPalettes } from './settingsPalettes';
import { useSettingsResource } from './useSettingsResource';

export const surface = {
  id: 'SET-ACTIVITY',
  title: 'Activity',
  where: 'Settings, Activity (web: /settings/activity)',
  status: 'in_progress',
  note: 'Periodic imports, paged history, import runs and source cleanup use the shared ProviderActivityView model from /api/v1/imports/activity/. The same endpoint supplies per-user MAL mapping tabs and outbound tracker delivery counts and delegates whitelisted actions to their existing web handlers. Browser comparisons are recorded separately; iOS and Android have not been exercised.',
};

function ActivityForm({ resource }) {
  const { settingsPalette, buttonPalette } = useSettingsPalettes();
  const activityPalette = { ...settingsPalette, pageCards: true, pageGap: 24,
    importRunCompletedText: palette.importRunCompletedText,
    importRunCompletedBackground: palette.importRunCompletedBackground };
  const [data, setData] = useState(resource.data);
  const [refreshKey, setRefreshKey] = useState(0);
  const [actionError, setActionError] = useState('');
  const [confirmMessage, setConfirmMessage] = useState('');
  const confirmRef = useRef(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; confirmRef.current?.(false); };
  }, []);
  const mapPresentation = payload => {
    const model = payload.presentation || {};
    return { ...Object.fromEntries(Object.entries(model).map(([key, value]) => [key,
      ['schedules', 'results', 'runs', 'cleanup'].includes(key) ? value.map(row => ({
        ...row, sourceLogo: absoluteUrl(resource.transport.serverUrl, row.sourceLogo),
      })) : value,
    ])), active: Boolean(model.active || payload.tracker_activity?.mal?.report?.is_active) };
  };
  async function fetchActivity({ page = 1 } = {}) {
    const next = await resource.transport.loadImportActivity({ page });
    if (mounted.current) setData(next);
    return mapPresentation(next);
  }
  async function act(path, values) {
    const result = await resource.transport.actImportActivity({ path, values });
    await fetchActivity();
    return result;
  }
  async function submit({ action, values }) {
    setActionError('');
    try {
      await act(action, values);
      setRefreshKey(value => value + 1);
      return true;
    } catch (error) {
      setActionError(error?.message || 'The activity action failed. Try again.');
      return false;
    }
  }
  function confirm(message) {
    return new Promise(resolve => { confirmRef.current = resolve; setConfirmMessage(message); });
  }
  function decide(approved) {
    confirmRef.current?.(approved);
    confirmRef.current = null;
    setConfirmMessage('');
  }
  async function refreshMappings() {
    const path = data.tracker_activity.actions.mal_full_sync_preview;
    let preview = await resource.transport.actImportActivity({ path, values: {} });
    const started = Date.now();
    const token = preview.token;
    while (preview.pending) {
      if (!mounted.current) throw new Error('Activity was closed.');
      if (Date.now() - started > 900000) throw new Error('Preview is taking too long. Check that the background Celery worker is running.');
      await new Promise(resolve => setTimeout(resolve, 1500));
      if (!mounted.current) throw new Error('Activity was closed.');
      preview = await resource.transport.actImportActivity({ path, values: { token } });
    }
    return preview.mapping_issues || [];
  }
  return <>
    <SettingsActivityView trackerActivity={data.tracker_activity} onTrackerAction={async (path, values) => {
      const result = await act(path, values); setRefreshKey(value => value + 1); return result;
    }}
      onRefreshMappings={refreshMappings}
      onMappingSearch={q => resource.transport.actImportActivity({ path: data.tracker_activity.actions.mal_mapping_search, values: { q } })}
      onMappingEpisodes={malId => resource.transport.actImportActivity({ path: data.tracker_activity.actions.mal_mapping_episodes, values: { mal_id: malId } })}
      importsContent={<ProviderActivityView key={refreshKey} initialData={mapPresentation(data)} showSources headingLevel={2}
        icons={{ schedules: settingsNavIcons.clock, history: actionIcons.historyClock, runs: actionIcons.historyClock, cleanup: actionIcons.trash }}
        onFetch={fetchActivity} onCopy={copyText} onSubmit={submit} onConfirm={confirm}
        labels={{ schedulesCopy: 'Automated imports that run on a schedule. These will continue to sync your media until disabled.',
          noSchedulesHint: 'Enable a recurring import or Plex watchlist sync to see it here',
          noHistoryHint: 'Import your media from any source to see the history here',
          cleanupWindow: 'Permanently delete everything of a media type imported from one source, e.g. before re-importing from a different source.' }}
        palette={activityPalette} buttonPalette={buttonPalette} />}
      palette={activityPalette} buttonPalette={buttonPalette} />
    {actionError ? <Text accessibilityRole="alert" style={{ color: settingsPalette.danger }}>{actionError}</Text> : null}
    <ConfirmDialog visible={Boolean(confirmMessage)} title="Are you sure?" message={confirmMessage}
      onConfirm={() => decide(true)} onCancel={() => decide(false)} palette={settingsPalette} buttonPalette={buttonPalette} />
  </>;
}

export default function ActivitySettingsSlot() {
  const resource = useSettingsResource(transport => transport.loadImportActivity());
  if (resource.state !== 'ready') {
    return <SettingsLoadState state={resource.state} message={resource.message} onRetry={resource.reload} />;
  }
  return <ActivityForm resource={resource} />;
}
