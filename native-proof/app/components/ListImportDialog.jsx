import React, { useEffect, useRef, useState } from 'react';
import { Linking, Modal, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { Button } from '../../../frontend/ui/Button';
import { MdblistConnect } from '../../../frontend/ui/MdblistConnect';
import { pickTextFile } from '../data/fileFlows';
import { palette, radius, spacing } from '../theme';

// Trakt, MDBList and CSV list imports over the JSON import endpoints. Trakt
// always uses the device-code flow: show the code, send the person to
// trakt.tv/activate, then poll until the server has the token.
const TITLES = { trakt: 'Import from Trakt', mdblist: 'Import from MDBList', csv: 'Import from CSV' };

export function ListImportDialog({ kind, transport, onClose, onDone }) {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [fields, setFields] = useState({ clientId: '', clientSecret: '', reference: '' });
  const [device, setDevice] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    let active = true;
    transport.loadImportStatus().then(payload => {
      if (active) setStatus(payload);
    }).catch(cause => {
      if (active) setError(cause?.message || 'The import status could not be loaded.');
    });
    return () => {
      active = false;
      clearTimeout(timer.current);
    };
  }, [transport]);

  const set = key => value => setFields(current => ({ ...current, [key]: value }));

  async function guard(work) {
    setBusy(true);
    setError('');
    try {
      return await work();
    } catch (cause) {
      setError(cause?.message || 'The import could not be started.');
      return null;
    } finally {
      setBusy(false);
    }
  }

  function finish(result) {
    setMessage(result?.detail || 'The import started in the background.');
    onDone?.(result?.detail);
  }

  async function pickCsv() {
    const result = await guard(async () => {
      const file = await pickTextFile();
      if (!file) return null;
      return transport.importCsv({ text: file.text });
    });
    if (result) finish(result);
  }

  async function connectMdblist(apiKey, frequency) {
    const result = await guard(() => transport.importMdblist({ action: 'connect', api_key: apiKey, sync_frequency: frequency }));
    if (result) {
      finish(result);
      setStatus(current => ({ ...current, mdblist: { ...(current?.mdblist || {}), connected: true } }));
    }
  }

  async function importMdblist() {
    const result = await guard(() => transport.importMdblist({ action: 'import', list_reference: fields.reference }));
    if (result) finish(result);
  }

  async function saveTraktCredentials() {
    const result = await guard(() => transport.importTrakt({
      action: 'credentials', client_id: fields.clientId, client_secret: fields.clientSecret,
    }));
    if (result) setStatus(current => ({ ...current, trakt: { has_credentials: true } }));
  }

  function poll(interval) {
    timer.current = setTimeout(async () => {
      try {
        const result = await transport.importTrakt({ action: 'poll' });
        if (result?.status === 'authorized') {
          setDevice(null);
          finish(result);
        } else {
          poll(interval);
        }
      } catch (cause) {
        setDevice(null);
        setError(cause?.message || 'The Trakt authorization failed.');
      }
    }, Math.max(2, Number(interval) || 5) * 1000);
  }

  async function startTrakt() {
    const result = await guard(() => transport.importTrakt({ action: 'start' }));
    if (result?.user_code) {
      setDevice(result);
      poll(result.interval);
    }
  }

  const done = Boolean(message);
  return <Modal transparent visible animationType="fade" onRequestClose={onClose}>
    <View style={styles.overlay}>
      <View style={styles.sheet} accessibilityViewIsModal>
        <Text style={styles.title}>{TITLES[kind]}</Text>
        {error ? <Text style={styles.error}>{error}</Text> : null}
        {done ? <Text style={styles.copy}>{message}</Text> : null}

        {!done && kind === 'csv' ? <>
          <Text style={styles.copy}>Choose a CSV file exported from Floppy. It is imported as a new list.</Text>
          <Button label={busy ? 'Importing...' : 'Choose CSV file'} tone="primary" disabled={busy} onPress={pickCsv} />
        </> : null}

        {!done && kind === 'mdblist' ? (status?.mdblist?.connected ? <>
          <Text style={styles.copy}>Paste an MDBList list URL or ID.</Text>
          <TextInput style={styles.input} value={fields.reference} onChangeText={set('reference')}
            placeholder="https://mdblist.com/lists/..." placeholderTextColor={palette.textMuted}
            autoCapitalize="none" autoCorrect={false} accessibilityLabel="MDBList list URL or ID" />
          <Button label={busy ? 'Importing...' : 'Import list'} tone="primary"
            disabled={busy || !fields.reference.trim()} onPress={importMdblist} />
        </> : status ? <MdblistConnect choices={status.mdblist.frequency_choices || []}
          defaultFrequency={status.mdblist.default_frequency} busy={busy} palette={palette}
          onConnect={connectMdblist} onCancel={onClose}
          onOpenPreferences={() => Linking.openURL('https://mdblist.com/preferences/').catch(() => setError('The link could not be opened.'))} /> : null) : null}

        {!done && kind === 'trakt' ? (device ? <>
          <Text style={styles.copy}>Enter this code at trakt.tv/activate, then come back. Floppy imports your lists when you approve.</Text>
          <Text style={styles.code} selectable>{device.user_code}</Text>
          <Button label="Open trakt.tv/activate" tone="surface"
            onPress={() => Linking.openURL(device.verification_url).catch(() => setError('The link could not be opened.'))} />
        </> : status?.trakt?.has_credentials ? <>
          <Text style={styles.copy}>Trakt credentials are saved. Authorize Floppy to import your lists.</Text>
          <Button label={busy ? 'Starting...' : 'Authorize Trakt'} tone="primary" disabled={busy} onPress={startTrakt} />
        </> : <>
          <Text style={styles.copy}>Create a Trakt API application at trakt.tv/oauth/applications, then enter its client ID. A client secret is optional.</Text>
          <TextInput style={styles.input} value={fields.clientId} onChangeText={set('clientId')}
            placeholder="Client ID" placeholderTextColor={palette.textMuted}
            autoCapitalize="none" autoCorrect={false} accessibilityLabel="Trakt client ID" />
          <TextInput style={styles.input} value={fields.clientSecret} onChangeText={set('clientSecret')}
            placeholder="Client secret (optional)" placeholderTextColor={palette.textMuted}
            autoCapitalize="none" autoCorrect={false} secureTextEntry accessibilityLabel="Trakt client secret" />
          <Button label={busy ? 'Saving...' : 'Save credentials'} tone="primary"
            disabled={busy || !fields.clientId.trim()} onPress={saveTraktCredentials} />
        </>) : null}

        {!(kind === 'mdblist' && !done && status && !status.mdblist.connected) ? <Pressable accessibilityRole="button" onPress={onClose} style={styles.close}>
          <Text style={styles.closeText}>{done ? 'Done' : 'Cancel'}</Text>
        </Pressable> : null}
      </View>
    </View>
  </Modal>;
}

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: palette.overlay, justifyContent: 'center', padding: spacing.lg },
  sheet: { backgroundColor: palette.surface, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.md },
  title: { color: palette.text, fontSize: 18, fontWeight: '700' },
  copy: { color: palette.textSecondary, fontSize: 14, lineHeight: 20 },
  error: { color: palette.danger, fontSize: 13 },
  code: { color: palette.text, fontSize: 28, fontWeight: '700', letterSpacing: 4, textAlign: 'center' },
  input: {
    color: palette.text,
    backgroundColor: palette.surfaceStrong,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    fontSize: 15,
  },
  close: { alignItems: 'center', paddingVertical: spacing.sm },
  closeText: { color: palette.textSecondary, fontSize: 14, fontWeight: '600' },
});
