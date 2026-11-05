import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import { Chip } from '../settings/Chip';
import { SelectField } from '../ui/SelectField';
import { SettingsCard } from '../settings/SettingsCard';
import { TextField } from '../ui/TextField';

const defaultPalette = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#52525b',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  badgeBorder: '#52525b',
  badgeBackground: '#3f3f46',
  badgeText: '#d4d4d8',
  badgeHover: '#52525b',
  radius: 6,
};

const defaultButtonPalette = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  'danger-solid': { background: '#dc2626', pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  radius: 6,
};

const defaultLabels = {
  connect: 'Connect',
  reconnect: 'Reconnect',
  addInstance: 'Add instance',
  saving: 'Connecting…',
  saved: 'Connection saved',
  saveError: 'Could not save the connection. Try again.',
  disconnect: 'Disconnect',
  disconnecting: 'Disconnecting…',
  disconnected: 'Connection removed',
  disconnectError: 'Could not disconnect. Try again.',
  edit: 'Edit connection',
  cancel: 'Cancel',
  connected: 'Connected',
  disconnectedStatus: 'Not connected',
  attention: 'Needs attention',
  connectedMessage: 'This account is connected.',
  disconnectedMessage: 'Connect an account to start syncing.',
  attentionMessage: 'The saved connection needs attention. Reconnect to continue.',
  close: 'Close',
};

function statusPalette(colors, tone) {
  if (tone === 'success') return { ...colors, badgeBorder: colors.success, badgeBackground: 'rgba(16, 185, 129, 0.15)', badgeText: '#a7f3d0' };
  if (tone === 'warning') return { ...colors, badgeBorder: colors.warning, badgeBackground: 'rgba(245, 158, 11, 0.15)', badgeText: '#fde68a' };
  if (tone === 'info') return { ...colors, badgeBorder: colors.accent, badgeBackground: 'rgba(99, 102, 241, 0.15)', badgeText: '#c7d2fe' };
  return colors;
}

function FieldControl({ field, value, onChange, colors }) {
  const common = {
    id: field.name,
    name: field.name,
    label: field.label,
    disabled: field.disabled,
    required: field.required,
    palette: colors,
  };
  if (field.type === 'select') {
    return <SelectField {...common} value={value ?? field.value ?? field.options?.[0]?.value}
      options={field.options || []} help={field.help}
      onChange={event => onChange(event.target.value)} />;
  }
  return <TextField {...common} type={field.type || 'text'} value={value}
    placeholder={field.placeholder} help={field.help} maskedPreview={field.maskedPreview}
    autoComplete="off" onChangeText={onChange} />;
}

/**
 * Shared account-connection card. Field metadata, status text and intents come
 * from the adapter; saved credentials and server URLs are never serialized here.
 */
export function AccountSettings({
  model,
  onConnect,
  onDisconnect,
  palette = {},
  buttonPalette = {},
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const labels = { ...defaultLabels, ...(model.labels || {}) };
  const [values, setValues] = useState({});
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const connected = Boolean(model.connected);
  const attention = Boolean(model.attention);
  const hasInstances = Boolean(model.instances?.length);
  const tone = model.statusTone || (connected ? 'success' : attention ? 'warning' : 'neutral');
  const status = model.statusLabel || (connected ? labels.connected : attention ? labels.attention : labels.disconnectedStatus);
  const message = model.message || model.messages?.[connected ? 'connected' : attention ? 'attention' : 'disconnected']
    || (connected ? labels.connectedMessage : attention ? labels.attentionMessage : labels.disconnectedMessage);
  const showForm = hasInstances || !connected || attention || editing;

  function change(name, value) {
    setValues(current => ({ ...current, [name]: value }));
    setNotice('');
    setError('');
  }

  async function submit() {
    if (pending) return;
    setPending('connect');
    setError('');
    setNotice('');
    try {
      await onConnect?.(values);
      setNotice(labels.saved);
      setEditing(false);
    } catch (reason) {
      setError(reason?.message || labels.saveError);
    } finally {
      setPending('');
    }
  }

  async function disconnect(instanceId) {
    if (pending) return;
    setPending(instanceId ? `disconnect-${instanceId}` : 'disconnect');
    setError('');
    setNotice('');
    try {
      await onDisconnect?.(instanceId);
      setValues({});
      setNotice(labels.disconnected);
    } catch (reason) {
      setError(reason?.message || labels.disconnectError);
    } finally {
      setPending('');
    }
  }

  return <SettingsCard title={model.title || 'Account connection'} badge={status}
    palette={statusPalette(colors, tone)}>
    {model.description ? <Text style={[styles.copy, { color: colors.textSecondary }]}>{model.description}</Text> : null}
    {model.badges?.length ? <View style={styles.badges}>{model.badges.map(badge =>
      <Chip key={badge.label} label={badge.label} palette={statusPalette(colors, badge.tone)} />)}</View> : null}
    {model.summary?.url || model.summary?.lastSync ? <Text style={[styles.copy, { color: colors.textMuted }]}>
      {[model.summary.url, model.summary.lastSync].filter(Boolean).join(' • ')}
    </Text> : null}
    {model.summary?.error ? <Text accessibilityRole="alert" style={[styles.copy, { color: colors.danger }]}>{model.summary.error}</Text> : null}
    {model.instances?.length ? <View style={styles.instances}>
      {model.instances.map(instance => <View key={instance.id} style={[styles.instance, { borderColor: colors.border }]}>
        <View style={styles.instanceHeading}>
          <Text style={[styles.instanceName, { color: colors.text }]}>{instance.name}</Text>
          <Chip label={instance.connected ? labels.connected : labels.disconnectedStatus}
            palette={statusPalette(colors, instance.connected ? 'success' : 'neutral')} />
        </View>
        <Text style={[styles.copy, { color: colors.textMuted }]}>{instance.url}</Text>
        {instance.error ? <Text style={[styles.copy, { color: colors.danger }]}>{instance.error}</Text> : null}
        <Button label={pending === `disconnect-${instance.id}` ? labels.disconnecting : labels.disconnect}
          tone="danger-solid" busy={pending === `disconnect-${instance.id}`} disabled={Boolean(pending)}
          onPress={() => disconnect(instance.id)} palette={buttons} />
      </View>)}
    </View> : <Text style={[styles.copy, { color: colors.textSecondary }]}>{message}</Text>}
    {showForm ? <View style={styles.fields}>
      {(model.fields || []).map(field => <FieldControl key={field.name} field={field}
        value={values[field.name]} onChange={value => change(field.name, value)} colors={colors} />)}
    </View> : null}
    {showForm ? <View style={styles.actions}>
      <Button label={pending === 'connect' ? labels.saving : (model.submitLabel || (editing || model.saved ? labels.reconnect : labels.connect))}
        busy={pending === 'connect'} disabled={Boolean(pending)} onPress={submit} palette={buttons} />
      {editing ? <Button label={labels.cancel} tone="surface" disabled={Boolean(pending)}
        onPress={() => setEditing(false)} palette={buttons} /> : null}
    </View> : null}
    {!showForm && !hasInstances && model.editable ? <View style={styles.actions}>
      <Button label={labels.edit} tone="surface" onPress={() => setEditing(true)} palette={buttons} />
    </View> : null}
    {model.saved && !hasInstances ? <View style={styles.actions}>
      <Button label={pending === 'disconnect' ? labels.disconnecting : labels.disconnect} tone="danger-solid"
        busy={pending === 'disconnect'} disabled={Boolean(pending)}
        onPress={() => disconnect()} palette={buttons} />
    </View> : null}
    {notice ? <Text accessibilityRole="status" style={[styles.copy, { color: colors.success }]}>{notice}</Text> : null}
    {error ? <Text accessibilityRole="alert" style={[styles.copy, { color: colors.danger }]}>{error}</Text> : null}
  </SettingsCard>;
}

const styles = StyleSheet.create({
  copy: { fontSize: 12, lineHeight: 17 },
  badges: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  instances: { gap: 10 },
  instance: { gap: 6, borderWidth: 1, borderRadius: 8, padding: 10 },
  instanceHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  instanceName: { flexShrink: 1, fontSize: 14, fontWeight: '600' },
  fields: { gap: 12 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
});
