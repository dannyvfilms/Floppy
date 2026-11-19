import React, { useEffect, useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { Button } from './Button';
import { SelectField } from './SelectField';
import { TextField } from './TextField';

// Credential input stays local to the presentation; only the submit event carries it.
export function MdblistConnect({ choices, defaultFrequency, busy, palette, onConnect, onCancel, onOpenPreferences }) {
  const [apiKey, setApiKey] = useState('');
  const [frequency, setFrequency] = useState(defaultFrequency || '');
  useEffect(() => setFrequency(defaultFrequency || ''), [defaultFrequency]);
  return <View style={{ gap: 16 }}>
    <Text style={{ color: palette.textSecondary, fontSize: 14, lineHeight: 20 }}>
      Import your MDBList lists as Floppy lists and keep them in sync. Get your API key from{' '}
      <Text accessibilityRole="link" onPress={onOpenPreferences} style={{ color: palette.accent }}>MDBList preferences</Text>.
    </Text>
    <TextField label="API Key" type="password" value={apiKey} onChangeText={setApiKey}
      placeholder="MDBList API Key" palette={palette} />
    <SelectField label="Sync Frequency" options={choices} value={frequency} palette={palette}
      onChange={event => setFrequency(event.target.value)} disabled={busy} />
    <View style={{ flexDirection: 'row', justifyContent: 'flex-end', alignItems: 'center', gap: 12 }}>
      <Pressable accessibilityRole="button" onPress={onCancel} style={{ padding: 8 }}>
        <Text style={{ color: palette.textSecondary }}>Cancel</Text>
      </Pressable>
      <Button label={busy ? 'Connecting...' : 'Connect & Import'} tone="primary"
        disabled={busy || !apiKey.trim() || !frequency} onPress={() => onConnect(apiKey, frequency)} />
    </View>
  </View>;
}
