import React, { useState } from 'react';
import { Button, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { NativeProofCard, NativeProofLabel } from '../frontend/ui/NativeProofCard';
import { Spinner } from '../frontend/ui/Spinner';
import { Badge } from '../frontend/ui/Badge';
import { loadMedia } from './mediaClient';

const palette = { background: '#27272a', border: '#52525b', placeholder: '#3f3f46', text: '#fafafa' };
const badgePalettes = {
  dark: { indigo: { color: '#fff', backgroundColor: '#4338ca' }, outline: { color: '#fff', borderColor: '#aaa', borderWidth: 1 } },
  light: { indigo: { color: '#fff', backgroundColor: '#4338ca' }, outline: { color: '#222', backgroundColor: '#fff', borderColor: '#555', borderWidth: 1 } },
};

export default function App() {
  const [server, setServer] = useState('');
  const [token, setToken] = useState('');
  const [items, setItems] = useState([]);
  const [message, setMessage] = useState('Enter your Floppy server URL and API token.');
  const [badgeDark, setBadgeDark] = useState(true);
  const [showSpinners, setShowSpinners] = useState(true);
  async function load() {
    try {
      setItems(await loadMedia(server, token));
      setMessage('Loaded your library. This proof is read-only.');
    } catch (error) {
      setItems([]);
      setMessage(error instanceof TypeError ? 'Could not reach the server. On web, open the proof from the same origin as Floppy; cross-origin requests require server CORS configuration.' : (error.message || 'Unable to load the library.'));
    }
  }
  return <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
    <NativeProofLabel text="Floppy native proof" color={palette.text} />
    {showSpinners && <View style={styles.rings}><Spinner size={12} color="#fff" /><Spinner size={16} color="#6366f1" /><Spinner size={20} color="#adb5bd" /></View>}
    <Button title="Toggle spinner examples" onPress={() => setShowSpinners(!showSpinners)} />
    <View style={styles.badges}>{['xs', 'sm', 'md', 'tag'].map(size => <Badge key={size} label={size.toUpperCase()} size={size} tone="indigo" palette={badgePalettes[badgeDark ? 'dark' : 'light']} />)}<Badge label="Details" size="md" palette={badgePalettes[badgeDark ? 'dark' : 'light']} onPress={() => setMessage('Badge pressed.')} /></View>
    <View style={{ width: 100 }}><Badge label="One line badge example" nowrap palette={badgePalettes[badgeDark ? 'dark' : 'light']} /></View>
    <Button title="Toggle badge theme" onPress={() => setBadgeDark(!badgeDark)} />
    <Text style={styles.text}>Server URL</Text>
    <TextInput accessibilityLabel="Server URL" autoCapitalize="none" autoCorrect={false} value={server} onChangeText={setServer} style={styles.input} />
    <Text style={styles.text}>API token</Text>
    <TextInput accessibilityLabel="API token" autoCapitalize="none" autoCorrect={false} secureTextEntry value={token} onChangeText={setToken} style={styles.input} />
    <Button title="Load library" onPress={load} />
    <Text accessibilityLiveRegion="polite" style={styles.text}>{message}</Text>
    <View style={styles.cards}>{items.map((item) => <NativeProofCard key={item.key} title={item.title} image={item.image} palette={palette} />)}</View>
  </ScrollView>;
}

const styles = StyleSheet.create({
  page: { flexGrow: 1, backgroundColor: '#18181b', padding: 24, gap: 12 },
  text: { color: '#fafafa' },
  input: { color: '#18181b', backgroundColor: '#fff', padding: 10, borderRadius: 4 },
  rings: { flexDirection: 'row', alignItems: 'center', gap: 16 },
  badges: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 12 },
  cards: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
});
