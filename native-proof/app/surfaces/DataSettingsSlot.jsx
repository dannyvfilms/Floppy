import React, { useEffect, useRef, useState } from 'react';
import { SettingsDataView } from '../../../frontend/pages/SettingsDataView';
import { SettingsPage } from '../../../frontend/pages/SettingsView';
import { RssFeedCard } from '../../../frontend/settings/DataSettings';
import { Icon } from '../../../frontend/ui/Icon';
import { actionIcons } from '../../../frontend/ui/actionIcons';
import { copyText, pickTextFile, saveTextFile } from '../data/fileFlows';
import {
  historyFromPayload,
  rssFeedUrl,
  rssFromPayload,
  schedulesFromPayload,
} from '../data/settingsTransport';
import SettingsLoadState from './SettingsLoadState';
import { useSettingsPalettes } from './settingsPalettes';
import { useSettingsResource } from './useSettingsResource';

const BLANK = { busy: false, error: '', success: '' };

function stamp() {
  return new Date().toISOString().replace(/[:T]/g, '-').slice(0, 19);
}

function DataForm({ transport, data, page, onOpenRss }) {
  const { settingsPalette, buttonPalette } = useSettingsPalettes();
  const initialSchedules = schedulesFromPayload(data.schedules);
  const [schedules, setSchedules] = useState(initialSchedules.schedules);
  const [history, setHistory] = useState(() => historyFromPayload(data.history));
  const [exportModel, setExportModel] = useState({
    frequency: 'once', time: '03:00',
    mediaTypes: initialSchedules.mediaTypes,
    selectedMediaTypes: initialSchedules.mediaTypes.map(type => type.value), includeLists: true, includeCollection: true,
  });
  const [exportStatus, setExportStatus] = useState(BLANK);
  const [scheduleStatus, setScheduleStatus] = useState({ ...BLANK, busyId: '' });
  const [restore, setRestore] = useState({ ...BLANK, fileName: '' });
  const backupRef = useRef('');
  const rss = rssFromPayload(data.rss);
  const [rssValues, setRssValues] = useState(() => {
    const first = rss.mediaTypes[0];
    return { mediaType: first?.value || '', rowKey: first?.rows?.[0]?.key || '', skipPlanning: true, skipCollected: true };
  });
  const [rssStatus, setRssStatus] = useState(BLANK);
  const [preview, setPreview] = useState({ state: 'idle', items: [] });
  const [maintenanceStatus, setMaintenanceStatus] = useState(BLANK);
  const [siteStatus, setSiteStatus] = useState(BLANK);
  const [importValues, setImportValues] = useState(() => ({
    frequency: data.importSettings?.frequency || 'once',
    time: data.importSettings?.time || '00:00',
    mode: data.importSettings?.mode || 'new',
  }));
  const [importStatus, setImportStatus] = useState(BLANK);

  const rssRows = (rss.mediaTypes.find(type => type.value === rssValues.mediaType)?.rows || [])
    .map(row => ({ value: row.key, label: row.title }));

  useEffect(() => {
    if (!rssValues.mediaType || !rssValues.rowKey) return undefined;
    let active = true;
    setPreview(current => ({ ...current, state: 'loading' }));
    transport.loadRssPreview(rssValues)
      .then(payload => {
        if (!active) return;
        const items = payload?.items || [];
        setPreview({ state: items.length ? 'ready' : 'empty', items });
      })
      .catch(() => { if (active) setPreview({ state: 'empty', items: [] }); });
    return () => { active = false; };
  }, [transport, rssValues]);

  async function refreshSchedules() {
    const [list, runs] = await Promise.all([transport.loadSchedules(), transport.loadExportHistory()]);
    setSchedules(schedulesFromPayload(list).schedules);
    setHistory(historyFromPayload(runs));
  }

  async function submitExport() {
    setExportStatus({ busy: true, error: '', success: '' });
    try {
      const scheduled = exportModel.frequency !== 'once';
      if (scheduled) await transport.createSchedule(exportModel);
      const csv = await transport.exportNow(exportModel);
      await saveTextFile({ name: `floppy_${stamp()}.csv`, text: typeof csv === 'string' ? csv : '', mimeType: 'text/csv' });
      if (scheduled) await refreshSchedules();
      setExportStatus({
        busy: false, error: '',
        success: scheduled ? 'Export saved. The first CSV is ready and the schedule is active.' : 'Export ready. Save the CSV from the file viewer.',
      });
    } catch (cause) {
      setExportStatus({ busy: false, error: cause?.message || 'Could not start the export.', success: '' });
    }
  }

  async function deleteSchedule(schedule) {
    setScheduleStatus({ busy: false, busyId: schedule.id, error: '', success: '' });
    try {
      await transport.deleteSchedule({ id: schedule.id });
      setSchedules(current => current.filter(item => item.id !== schedule.id));
      setScheduleStatus({ busy: false, busyId: '', error: '', success: 'Backup schedule deleted.' });
    } catch (cause) {
      setScheduleStatus({ busy: false, busyId: '', error: cause?.message || 'Could not delete the schedule.', success: '' });
      throw cause;
    }
  }

  async function chooseBackup() {
    setRestore(current => ({ ...current, error: '', success: '' }));
    try {
      const picked = await pickTextFile();
      if (!picked) return;
      backupRef.current = picked.text;
      setRestore({ ...BLANK, fileName: picked.name });
    } catch (cause) {
      setRestore(current => ({ ...current, error: cause?.message || 'The file could not be read.' }));
    }
  }

  async function restoreBackup() {
    setRestore(current => ({ ...current, busy: true, error: '', success: '' }));
    try {
      await transport.restoreBackup({ content: backupRef.current });
      setRestore(current => ({ ...current, busy: false, success: 'Restore queued. Progress appears under import activity.' }));
    } catch (cause) {
      setRestore(current => ({ ...current, busy: false, error: cause?.message || 'Could not restore the backup.' }));
      throw cause;
    }
  }

  async function copyFeed() {
    const url = rssFeedUrl(rss.template, rssValues);
    try {
      await copyText(url);
      setRssStatus({ busy: false, error: '', success: 'Feed URL copied.' });
    } catch {
      setRssStatus({ busy: false, error: 'The feed URL could not be copied.', success: '' });
    }
  }

  async function maintain(action, body, message) {
    setMaintenanceStatus({ busy: true, error: '', success: '' });
    try {
      const result = await action(body);
      setMaintenanceStatus({ busy: false, error: '', success: result?.messages?.[0] || message });
    } catch (cause) {
      setMaintenanceStatus({ busy: false, error: cause?.message || 'The action failed.', success: '' });
      throw cause;
    }
  }

  async function exportLetterboxd() {
    setSiteStatus({ busy: true, error: '', success: '' });
    try {
      const csv = await transport.exportLetterboxd();
      await saveTextFile({ name: `letterboxd_${stamp()}.csv`, text: typeof csv === 'string' ? csv : '', mimeType: 'text/csv' });
      setSiteStatus({ busy: false, error: '', success: 'Letterboxd export ready.' });
    } catch (cause) {
      setSiteStatus({ busy: false, error: cause?.message || 'Could not export for Letterboxd.', success: '' });
    }
  }

  async function changeImportSettings(next) {
    const previous = importValues;
    setImportValues(next);
    setImportStatus({ busy: true, error: '', success: '' });
    try {
      const saved = await transport.saveImportSettings(next);
      setImportValues({ frequency: saved.frequency, time: saved.time, mode: saved.mode });
      setImportStatus({ busy: false, error: '', success: 'Import settings saved.' });
    } catch (cause) {
      setImportValues(previous);
      setImportStatus({ busy: false, error: cause?.message || 'Could not save import settings.', success: '' });
    }
  }

  async function downloadTemplate() {
    setMaintenanceStatus({ busy: true, error: '', success: '' });
    try {
      const csv = await transport.downloadImportTemplate();
      await saveTextFile({ name: 'floppy-import-template.csv', text: typeof csv === 'string' ? csv : '', mimeType: 'text/csv' });
      setMaintenanceStatus({ busy: false, error: '', success: 'Import template ready.' });
    } catch (cause) {
      setMaintenanceStatus({ busy: false, error: cause?.message || 'Could not download the template.', success: '' });
    }
  }

  const rssModel = {
    sessionRequired: Boolean(data.rss?.sessionRequired),
    mediaTypes: rss.mediaTypes.map(type => ({ value: type.value, label: type.label })),
    rows: rssRows,
    values: rssValues,
    feedUrl: rssFeedUrl(rss.template, rssValues),
    preview: { state: preview.state, title: '', items: preview.items },
  };

  const rssProps = {
    model: rssModel, ...rssStatus, onCopy: copyFeed,
    onChange: values => {
      const type = rss.mediaTypes.find(entry => entry.value === values.mediaType);
      const rowValid = type?.rows?.some(row => row.key === values.rowKey);
      setRssValues({ ...values, rowKey: rowValid ? values.rowKey : (type?.rows?.[0]?.key || '') });
    },
  };
  if (page === 'rss') return <SettingsPage heading={false} palette={settingsPalette}>
    <RssFeedCard {...rssProps} model={{ ...rssModel, labels: { rssTitle: 'RSS' } }}
      palette={{ ...settingsPalette, pageCards: true }} buttonPalette={buttonPalette} />
  </SettingsPage>;

  return <SettingsDataView
    onOpenRss={onOpenRss}
    onDownloadTemplate={downloadTemplate}
    sites={{ icon: <Icon spec={actionIcons.externalLink} color={settingsPalette.link} size={24} />, ...siteStatus, onLetterboxd: exportLetterboxd }}
    importSettings={{
      values: importValues,
      frequencies: (data.importSettings?.frequencies || []),
      modes: (data.importSettings?.modes || []),
      ...importStatus,
      onChange: changeImportSettings,
    }}
    schedule={{ icon: <Icon spec={actionIcons.exportFile} color={settingsPalette.link} size={24} />, backup: data.backup?.sections || [], model: exportModel, ...exportStatus, onChange: setExportModel, onSubmit: submitExport }}
    scheduled={{ icon: <Icon spec={actionIcons.repeat} color={settingsPalette.link} size={24} />, schedules, ...scheduleStatus, onDelete: deleteSchedule }}
    history={{ icon: <Icon spec={actionIcons.historyClock} color={settingsPalette.link} size={24} />, results: history }}
    restore={{ fileName: restore.fileName, busy: restore.busy, error: restore.error, success: restore.success, onChoose: chooseBackup, onRestore: restoreBackup }}
    rss={rssProps}
    maintenance={{
      mediaTypes: data.maintenance?.media_types || [],
      duplicateAnimeCount: data.maintenance?.duplicate_anime_count || 0,
      ...maintenanceStatus,
      onDownloadTemplate: downloadTemplate,
      onRepairAnime: () => maintain(transport.runLibraryMaintenance, { action: 'repair_anime_libraries' }, 'Repairing duplicated anime libraries in the background.').catch(() => {}),
      onDelete: ({ mediaType, deleteMetadata }) => maintain(
        transport.runLibraryMaintenance,
        { action: 'delete_media_type', media_type: mediaType, delete_metadata: deleteMetadata },
        'Library entries deleted.',
      ),
    }}
    palette={{ ...settingsPalette, pageCards: true }} buttonPalette={buttonPalette} />;
}

export default function DataSettingsSlot({ page = 'data', onOpenRss }) {
  const resource = useSettingsResource(async transport => {
    const [schedules, history, rss, maintenance, backup, importSettings] = await Promise.all([
      transport.loadSchedules(),
      transport.loadExportHistory(),
      transport.canManageCredentials ? transport.loadRss() : Promise.resolve({ sessionRequired: true }),
      transport.loadLibraryMaintenance().catch(() => ({ media_types: [] })),
      transport.loadBackupStatus().catch(() => ({ sections: [] })),
      transport.loadImportSettings().catch(() => null),
    ]);
    return { schedules, history, rss, maintenance, backup, importSettings };
  });
  if (resource.state !== 'ready') {
    return <SettingsLoadState state={resource.state} message={resource.message} onRetry={resource.reload} />;
  }
  return <DataForm transport={resource.transport} data={resource.data} page={page} onOpenRss={onOpenRss} />;
}
