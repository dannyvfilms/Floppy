import React, { useState } from 'react';
import { Button, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { NativeProofCard, NativeProofLabel } from '../frontend/ui/NativeProofCard';
import { Spinner } from '../frontend/ui/Spinner';
import { Badge } from '../frontend/ui/Badge';
import { ProgressChanger } from '../frontend/ui/ProgressChanger';
import { loadMedia } from './mediaClient';

const palette = { background: '#27272a', border: '#52525b', placeholder: '#3f3f46', text: '#fafafa' };
const progressPalettes = {
  dark: { text: '#e4e4e7', icon: '#fafafa', disabledIcon: '#a1a1aa', button: '#3f3f46', buttonHover: '#52525b', flash: 'rgba(99, 102, 241, 0.55)', buttonSize: 24, radius: 6, iconSize: 12, fontSize: 12, minWidth: 24, showButtons: true },
  light: { text: '#1f2937', icon: '#18181b', disabledIcon: '#71717a', button: '#e4e4e7', buttonHover: '#d4d4d8', flash: 'rgba(99, 102, 241, 0.55)', buttonSize: 24, radius: 6, iconSize: 12, fontSize: 12, minWidth: 24, showButtons: true },
};
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
  const [progressDark, setProgressDark] = useState(true);
  const [progressValue, setProgressValue] = useState(3);
  const [progressBusy, setProgressBusy] = useState(null);
  function adjustProgress(operation) {
    const next = Math.max(0, Math.min(10, progressValue + (operation === 'increase' ? 1 : -1)));
    setProgressBusy(operation);
    setProgressValue(next);
    setTimeout(() => setProgressBusy(null), 500);
  }
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
    <Text style={styles.section}>Progress controls</Text>
    <ProgressChanger value={String(progressValue)} max="10" unit="Episodes" showMax
      canDecrease={progressValue > 0} canIncrease={progressValue < 10} busyOperation={progressBusy}
      decreaseLabel="Decrease progress" increaseLabel="Increase progress" onAdjust={adjustProgress}
      palette={progressPalettes[progressDark ? 'dark' : 'light']} />
    <ProgressChanger value="0" max="10" unit="Episodes" showMax canDecrease={false} canIncrease
      decreaseLabel="Decrease progress" increaseLabel="Increase progress" palette={progressPalettes[progressDark ? 'dark' : 'light']} />
    <ProgressChanger value="10" max="10" unit="Episodes" showMax canDecrease canIncrease={false}
      decreaseLabel="Decrease progress" increaseLabel="Increase progress" palette={progressPalettes[progressDark ? 'dark' : 'light']} />
    <View style={styles.lightSurface}>
      <Text style={styles.lightLabel}>Light palette</Text>
      <ProgressChanger value="3" max="10" unit="Episodes" showMax canDecrease canIncrease
        decreaseLabel="Decrease progress" increaseLabel="Increase progress" palette={progressPalettes.light} />
    </View>
    <Button title="Toggle progress theme" onPress={() => setProgressDark(!progressDark)} />
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
  section: { color: '#fafafa', fontSize: 16, fontWeight: '600', marginTop: 8 },
  lightSurface: { backgroundColor: '#f4f4f5', borderRadius: 8, padding: 12, gap: 8 },
  lightLabel: { color: '#18181b', fontWeight: '600' },
  input: { color: '#18181b', backgroundColor: '#fff', padding: 10, borderRadius: 4 },
  rings: { flexDirection: 'row', alignItems: 'center', gap: 16 },
  badges: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 12 },
  cards: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
});
