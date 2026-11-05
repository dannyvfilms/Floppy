import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from './Button';
import { SettingsCard } from '../settings/SettingsCard';

const defaultPalette = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  background: '#27272a',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  success: '#10b981',
  danger: '#ef4444',
  badgeBorder: '#52525b',
  badgeBackground: '#3f3f46',
  badgeText: '#d4d4d8',
  badgeHover: '#52525b',
  radius: 8,
  focusStyle: {},
};

const defaultButtonPalette = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  radius: 6,
  focusStyle: {},
};

const defaultCopy = {
  title: 'Install Floppy',
  description: 'Floppy is an installable PWA. Add it to your Home Screen to launch it like an app directly from your browser.',
  installLabel: 'Install Floppy',
  guideLabel: 'Installation guide',
  installedBadge: 'Installed',
  webBadge: 'Web install',
  accepted: 'Installing Floppy. Look for it alongside your other apps.',
  dismissed: 'Installation dismissed. You can still add Floppy using the steps below.',
  failed: 'Your browser could not open the install prompt. Use the steps below instead.',
  unavailable: 'The install prompt is not available right now. Use the steps below instead.',
  nativeStatus: 'Floppy is installed on this device. Open it from the Home Screen or the app switcher.',
  noControl: 'No install control anywhere? Serve the instance over HTTPS and open it in a full browser rather than an in-app one. Tracking still needs a connection to your Floppy server.',
  steps: {
    ios: {
      title: 'iOS and iPadOS',
      items: ['Open this instance in Safari.', 'Tap the Share button.', 'Choose Add to Home Screen.', 'Turn on Open as Web App if it is shown, then tap Add.'],
    },
    android: {
      title: 'Android',
      items: ['Open this instance in Chrome.', 'Open the browser menu.', 'Choose Add to Home screen.', "Confirm with Install, following your browser's wording."],
    },
    desktop: {
      title: 'Desktop',
      items: ['Open this instance in a full browser rather than an in-app one.', 'Use the browser install control in the address bar or menu.', 'Open the installation guide for the iOS and Android steps.'],
    },
    native: {
      title: 'Native app',
      items: ['This app is already installed.', 'Updates arrive through the app distribution channel.', 'Use the guide for the browser app on another device.'],
    },
  },
};

/** Install/launch feedback. Browser state and prompt handling come from the
 * platform adapter; this component only presents availability, outcomes and the
 * one-step platform instructions.
 */
export function InstallPromptCard({
  state = {},
  onInstall,
  onOpenGuide,
  palette = {},
  buttonPalette = {},
  copy = {},
  busy = false,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const text = { ...defaultCopy, ...copy, steps: { ...defaultCopy.steps, ...(copy.steps || {}) } };
  const platform = state.platform || 'desktop';
  const steps = text.steps[platform] || text.steps.desktop;
  const [status, setStatus] = useState('');
  const [pending, setPending] = useState(false);
  const [attempted, setAttempted] = useState(false);

  const install = async () => {
    if (!onInstall || pending) return;
    setPending(true);
    setStatus('');
    setAttempted(true);
    try {
      const result = await onInstall();
      setStatus(text[result?.outcome] || text.unavailable);
    } catch (error) {
      setStatus(text.failed);
    } finally {
      setPending(false);
    }
  };

  const showNativeStatus = platform === 'native' && !status;
  const message = showNativeStatus ? text.nativeStatus : status;
  const tone = status === text.failed || status === text.unavailable
    ? colors.danger
    : status ? colors.success : colors.textMuted;

  return <SettingsCard title={text.title} badge={state.installed || state.standalone ? text.installedBadge : text.webBadge}
    palette={colors}>
    <Text style={[styles.copy, { color: colors.textSecondary }]}>{text.description}</Text>
    {state.canInstall && !attempted ? <View style={styles.action}>
      <Button label={text.installLabel} busy={pending || busy} onPress={install} palette={buttons} />
    </View> : null}
    {message ? <Text accessibilityLiveRegion="polite" role="status" style={[styles.status, { color: tone }]}>{message}</Text> : null}
    <View style={[styles.steps, { borderColor: colors.border, backgroundColor: colors.surfaceStrong }]}>
      <Text role="heading" aria-level={5} style={[styles.stepsTitle, { color: colors.text }]}>{steps.title}</Text>
      {steps.items.map((item, index) => <Text key={`${steps.title}-${index}`} style={[styles.step, { color: colors.textMuted }]}>{`${index + 1}. ${item}`}</Text>)}
    </View>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{text.noControl}</Text>
    {onOpenGuide ? <View style={styles.action}>
      <Button label={text.guideLabel} tone="surface" onPress={onOpenGuide} palette={buttons} />
    </View> : null}
  </SettingsCard>;
}

const styles = StyleSheet.create({
  copy: { fontSize: 13, lineHeight: 19 },
  action: { alignItems: 'flex-start' },
  status: { fontSize: 12, lineHeight: 17, fontWeight: '600' },
  steps: { borderWidth: 1, borderRadius: 8, padding: 12, gap: 4 },
  stepsTitle: { fontSize: 13, fontWeight: '600' },
  step: { fontSize: 12, lineHeight: 18 },
});
