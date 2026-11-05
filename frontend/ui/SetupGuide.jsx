import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from './Button';
import { SettingsCard } from '../settings/SettingsCard';

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
  danger: '#ef4444',
  warning: '#f59e0b',
  success: '#10b981',
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
  showSteps: 'Show steps',
  hideSteps: 'Hide steps',
  copy: 'Copy',
  copied: 'Copied',
  copyFailed: 'Could not copy',
  close: 'Close',
};

function badgePalette(colors, tone) {
  if (tone === 'warning') return { ...colors, badgeBorder: colors.warning, badgeBackground: 'rgba(245, 158, 11, 0.15)', badgeText: '#fde68a' };
  if (tone === 'success') return { ...colors, badgeBorder: colors.success, badgeBackground: 'rgba(16, 185, 129, 0.15)', badgeText: '#a7f3d0' };
  if (tone === 'info') return { ...colors, badgeBorder: colors.accent, badgeBackground: 'rgba(99, 102, 241, 0.15)', badgeText: '#c7d2fe' };
  return colors;
}

function CopyValue({ value, colors, buttonPalette, labels, state, onCopy }) {
  return <View style={[styles.copyRow, { borderColor: colors.border, backgroundColor: colors.background }]}>
    <Text selectable style={[styles.code, { color: colors.textSecondary }]}>{value}</Text>
    <Button
      label={state === 'copied' ? labels.copied : state === 'error' ? labels.copyFailed : labels.copy}
      tone="surface"
      busy={state === 'copying'}
      onPress={() => onCopy(value)}
      palette={buttonPalette}
    />
  </View>;
}

function Parts({ parts, copy, colors, buttonPalette, labels, copyState, onCopy, onOpenLink }) {
  const inline = parts.filter(part => part[0] !== 'copy');
  const copies = parts.filter(part => part[0] === 'copy');
  return <View style={styles.partGroup}>
    {inline.length ? <Text style={[styles.body, { color: colors.textSecondary }]}>
      {inline.map((part, index) => {
        const [kind, text, url] = part;
        if (kind === 'b') return <Text key={index} style={[styles.body, styles.bold, { color: colors.text }]}>{text}</Text>;
        if (kind === 'em') return <Text key={index} style={[styles.body, styles.emphasis]}>{text}</Text>;
        if (kind === 'code') return <Text key={index} style={[styles.code, { color: colors.text }]}>{text}</Text>;
        if (kind === 'a' || kind === 'clink') return <Text key={index} accessibilityRole="link"
          onPress={() => onOpenLink?.(kind === 'clink' ? copy[url] : url, text)}
          style={[styles.body, styles.link, { color: colors.accent }]}>{text}</Text>;
        return <Text key={index}>{text}</Text>;
      })}
    </Text> : null}
    {copies.length ? <View style={styles.inlineCopies}>
      {copies.map((part, index) => <CopyValue key={`copy-${index}`}
        value={copy[part[1]] || ''} colors={colors} buttonPalette={buttonPalette}
        labels={labels} state={copyState[part[1]]} onCopy={value => onCopy(value, part[1])} />)}
    </View> : null}
  </View>;
}

function Steps({ steps, copy, colors, buttonPalette, labels, copyState, onCopy, onOpenLink }) {
  return <View style={styles.steps}>
    {steps.map((step, index) => {
      const parts = Array.isArray(step) ? step : step.parts;
      return <View key={index} style={styles.step}>
        <Text style={[styles.stepNumber, { borderColor: colors.border, color: colors.textMuted }]}>{index + 1}</Text>
        <View style={styles.stepBody}>
          <Parts parts={parts} copy={copy} colors={colors} buttonPalette={buttonPalette}
            labels={labels} copyState={copyState} onCopy={onCopy} onOpenLink={onOpenLink} />
          {step.items ? <View style={styles.items}>{step.items.map((item, itemIndex) =>
            <View key={itemIndex} style={styles.itemRow}>
              <Text style={[styles.body, { color: colors.textMuted }]}>•</Text>
              <Parts parts={item} copy={copy} colors={colors} buttonPalette={buttonPalette}
                labels={labels} copyState={copyState} onCopy={onCopy} onOpenLink={onOpenLink} />
            </View>)}</View> : null}
        </View>
      </View>;
    })}
  </View>;
}

/**
 * Shared setup-guide presentation. Copy values, links and their transport are
 * supplied by the caller; the browser adapter keeps token-bearing URLs in the
 * server fallback and a native adapter owns clipboard access.
 */
export function SetupGuide({
  guide,
  copy = {},
  onCopy,
  onOpenLink,
  labels,
  palette = {},
  buttonPalette = {},
}) {
  const [open, setOpen] = useState(!guide.collapsed);
  const [copyState, setCopyState] = useState({});
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const text = { ...defaultLabels, ...labels };
  const badge = guide.badge ? badgePalette(colors, guide.badge.tone) : colors;

  async function copyValue(value, key) {
    if (!value) return;
    if (!onCopy) {
      setCopyState(current => ({ ...current, [key]: 'error' }));
      return;
    }
    setCopyState(current => ({ ...current, [key]: 'copying' }));
    try {
      await onCopy(value, key);
      setCopyState(current => ({ ...current, [key]: 'copied' }));
    } catch {
      setCopyState(current => ({ ...current, [key]: 'error' }));
    }
  }

  const intro = <>
    {!guide.bare && guide.description ? <Text style={[styles.body, { color: colors.textSecondary }]}>{guide.description}</Text> : null}
    {guide.warning ? <View style={[styles.warning, { borderColor: colors.warning }]}>
      <Text style={[styles.body, styles.bold, { color: colors.text }]}>{guide.warning.title}</Text>
      <Text style={[styles.body, { color: colors.textSecondary }]}>{guide.warning.text}</Text>
    </View> : null}
    {guide.badge?.summary ? <Text style={[styles.body, { color: colors.textMuted }]}>{guide.badge.summary}</Text> : null}
    {guide.primary ? <View style={styles.primary}>
      <Text style={[styles.label, { color: colors.textMuted }]}>{guide.primary.label}</Text>
      <CopyValue value={copy[guide.primary.key] || ''} colors={colors}
        buttonPalette={buttons} labels={text} state={copyState[guide.primary.key]}
        onCopy={value => copyValue(value, guide.primary.key)} />
    </View> : null}
  </>;

  const steps = <>
    {guide.collapsed ? <Button label={open ? text.hideSteps : text.showSteps} tone="surface"
      onPress={() => setOpen(value => !value)} palette={buttons} /> : null}
    {open ? <>
      {guide.methods ? guide.methods.map(method => <View key={method.title} style={styles.method}>
        <Text role="heading" aria-level={4} style={[styles.methodTitle, { color: colors.text }]}>{method.title}</Text>
        {method.description ? <Text style={[styles.body, { color: colors.textSecondary }]}>{method.description}</Text> : null}
        <Steps steps={method.steps} copy={copy} colors={colors} buttonPalette={buttons}
          labels={text} copyState={copyState} onCopy={copyValue} onOpenLink={onOpenLink} />
      </View>) : <>
        {guide.heading ? <Text role="heading" aria-level={4} style={[styles.heading, { color: colors.text }]}>{guide.heading}</Text> : null}
        <Steps steps={guide.steps || []} copy={copy} colors={colors} buttonPalette={buttons}
          labels={text} copyState={copyState} onCopy={copyValue} onOpenLink={onOpenLink} />
      </>}
    </> : null}
  </>;

  if (guide.bare) return <View style={styles.content}>{intro}{steps}</View>;

  return <SettingsCard title={guide.title} badge={guide.badge?.label} palette={badge}>
    {intro}
    {steps}
  </SettingsCard>;
}

const styles = StyleSheet.create({
  content: { gap: 12, minWidth: 0 },
  body: { fontSize: 13, lineHeight: 19 },
  bold: { fontWeight: '700' },
  emphasis: { fontStyle: 'italic' },
  code: { fontFamily: 'Courier', fontSize: 12 },
  link: { textDecorationLine: 'underline' },
  label: { fontSize: 12, fontWeight: '600' },
  primary: { gap: 6 },
  copyRow: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: 8, padding: 8 },
  inlineCopies: { gap: 6 },
  partGroup: { gap: 4, flexShrink: 1 },
  itemRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 6 },
  warning: { borderLeftWidth: 3, paddingLeft: 10, gap: 2 },
  heading: { fontSize: 14, fontWeight: '600' },
  method: { gap: 6 },
  methodTitle: { fontSize: 14, fontWeight: '600' },
  steps: { gap: 10 },
  step: { flexDirection: 'row', gap: 8 },
  stepNumber: { width: 22, height: 22, borderRadius: 11, borderWidth: 1, textAlign: 'center', fontSize: 11, lineHeight: 20 },
  stepBody: { flexShrink: 1, gap: 4 },
  items: { gap: 3 },
});
