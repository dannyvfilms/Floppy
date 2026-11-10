import React, { useState } from 'react';
import { Linking } from 'react-native';
import { SettingsAdvancedView } from '../../../frontend/pages/SettingsAdvancedView';
import { SettingsCard } from '../../../frontend/settings/SettingsCard';
import { Icon } from '../../../frontend/ui/Icon';
import { settingsNavIcons } from '../settingsNavIcons';
import { saveTextFile } from '../data/fileFlows';
import { advancedFromPayload } from '../data/settingsTransport';
import SettingsLoadState from './SettingsLoadState';
import { useSettingsPalettes } from './settingsPalettes';
import { useSettingsResource } from './useSettingsResource';

export const surface = {
  id: 'SET-SYSTEM',
  title: 'Advanced',
  where: 'System, cache, image cache, logs and server port',
  status: 'in_progress',
  note: 'State loads from /api/v1/user/advanced/ (superuser fields are only filled for superusers, and the controls are hidden from the same flag). Cache clears, image cache toggle/clear and the server port save/reset call /api/v1/user/advanced/..., and the sanitized log download streams from /api/v1/user/advanced/logs/ into data/fileFlows. The server re-checks superuser access on every write. Browser and device runtime interaction were not exercised.',
};

function stamp() {
  return new Date().toISOString().replace(/[:T]/g, '-').slice(0, 19);
}

function AdvancedBody({ transport, payload }) {
  const { settingsPalette, buttonPalette } = useSettingsPalettes();
  const initial = advancedFromPayload(payload);
  const [logs, setLogs] = useState({ busy: false, success: '', error: '' });
  const [image, setImage] = useState({ enabled: initial.imageCache.enabled, count: initial.imageCache.count, size: initial.imageCache.size, busy: false, success: '', error: '' });
  const [cache, setCache] = useState({ busyKind: '', success: '', error: '' });
  const [port, setPort] = useState(initial.serverPort);
  const [portStatus, setPortStatus] = useState({ busy: false, success: '', error: '' });

  const openUrl = url => { if (url) Linking.openURL(url).catch(() => {}); };

  async function downloadLogs() {
    setLogs({ busy: true, success: '', error: '' });
    try {
      const text = await transport.downloadLogs();
      await saveTextFile({ name: `floppy-logs-${stamp()}.txt`, text: typeof text === 'string' ? text : '', mimeType: 'text/plain' });
      setLogs({ busy: false, success: 'Sanitized logs saved. Secrets were redacted by the server.', error: '' });
    } catch (cause) {
      setLogs({ busy: false, success: '', error: cause?.message || 'Could not download the logs.' });
    }
  }

  async function saveImageCache(enabled) {
    setImage(current => ({ ...current, busy: true, success: '', error: '' }));
    try {
      const result = await transport.setImageCache(enabled);
      setImage(current => ({ ...current, enabled: Boolean(result.imageEnabled), busy: false, success: result.message || '' }));
    } catch (cause) {
      setImage(current => ({ ...current, busy: false, error: cause?.message || 'Could not update image caching.' }));
    }
  }

  async function clearImageCache() {
    setImage(current => ({ ...current, busy: true, success: '', error: '' }));
    try {
      const result = await transport.clearImageCache();
      setImage(current => ({
        ...current, count: result.imageCount ?? current.count, size: result.imageSize ?? current.size,
        busy: false, success: result.message || '',
      }));
    } catch (cause) {
      setImage(current => ({ ...current, busy: false, error: cause?.message || 'Could not clear the image cache.' }));
    }
  }

  async function clearCache(kind) {
    setCache({ busyKind: kind, success: '', error: '' });
    try {
      const result = await transport.clearCache(kind);
      setCache({ busyKind: '', success: result.message || result.messages?.[0] || 'Cache cleared.', error: '' });
    } catch (cause) {
      setCache({ busyKind: '', success: '', error: cause?.message || 'Could not clear the cache.' });
    }
  }

  async function applyPortResult(action) {
    setPortStatus({ busy: true, success: '', error: '' });
    try {
      const result = await action();
      if (result?.serverPort) setPort(current => ({ ...current, ...result.serverPort }));
      setPortStatus({ busy: false, success: result?.message || '', error: '' });
    } catch (cause) {
      setPortStatus({ busy: false, success: '', error: cause?.message || 'Could not update the server port.' });
    }
  }

  return <SettingsCard title="Advanced" palette={{ ...settingsPalette, pageCards: true }}
    icon={<Icon spec={settingsNavIcons['vertical-sliders']} color={settingsPalette.link} size={24} />}>
    <SettingsAdvancedView heading={false} labels={payload.labels || {}} icons={payload.icons || {}}
    logs={{ ...initial.logs, ...logs, onDownloadLogs: downloadLogs, onOpenUrl: openUrl }}
    imageCache={{ isSuperuser: initial.isSuperuser, ...image, onSave: saveImageCache, onClear: clearImageCache }}
    cacheManagement={{ ...cache, onClear: clearCache }}
    serverPort={{
      ...port, canManage: initial.isSuperuser, ...portStatus,
      onSave: value => applyPortResult(() => transport.saveServerPort(value)),
      onReset: () => applyPortResult(() => transport.resetServerPort()),
    }}
    palette={{ ...settingsPalette, pageCards: true }} buttonPalette={buttonPalette} />
  </SettingsCard>;
}

export default function AdvancedSettingsSlot() {
  const resource = useSettingsResource(transport => transport.loadAdvanced());
  if (resource.state !== 'ready') {
    return <SettingsLoadState state={resource.state} message={resource.message} onRetry={resource.reload} />;
  }
  return <AdvancedBody transport={resource.transport} payload={resource.data} />;
}
