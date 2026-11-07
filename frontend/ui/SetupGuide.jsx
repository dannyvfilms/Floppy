import React, { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Button } from './Button';
import { Tooltip } from './controls/Tooltip';
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
  return { ...colors, badgeBackground: colors.surface };
}

function CopyValue({ value, label, colors, buttonPalette, labels, state, onCopy, boxed = false }) {
  return <View style={[styles.copyRow, boxed && { backgroundColor: colors.surface, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8 }]}>
    <Text selectable style={[styles.code, styles.codeBlock, { color: colors.text }]}>{value}</Text>
    <Button
      label={state === 'copied' ? labels.copied : state === 'error' ? labels.copyFailed : labels.copy}
      tone="surface"
      size="sm"
      width="auto"
      accessibilityLabel={label ? `${labels.copy} ${label}` : labels.copy}
      busy={state === 'copying'}
      onPress={() => onCopy(value)}
      palette={buttonPalette}
    />
  </View>;
}

function PreBlock({ text, colors, buttonPalette, labels, state, onCopy }) {
  return <View style={styles.preBlock}>
    <ScrollView style={[styles.pre, { backgroundColor: colors.surface }]} nestedScrollEnabled>
      <Text selectable style={[styles.preText, { color: colors.text }]}>{text}</Text>
    </ScrollView>
    <Button label={state === 'copied' ? labels.copied : state === 'error' ? labels.copyFailed : labels.copy}
      tone="surface" size="sm" width="full" busy={state === 'copying'}
      onPress={() => onCopy(text)} palette={buttonPalette} />
  </View>;
}

// Inline runs keep release spacing: each authored fragment is separated by a
// space, matching the legacy markup that padded every bold/code/link span.
function InlineParts({ parts, colors, copy, onOpenLink }) {
  return <Text style={[styles.body, { color: colors.textSecondary }]}>
    {parts.map((part, index) => {
      const [kind, text, url] = part;
      const separator = index < parts.length - 1 ? ' ' : '';
      if (kind === 'b') return <Text key={index} style={[styles.body, styles.bold, { color: colors.text }]}>{`${text}${separator}`}</Text>;
      if (kind === 'em') return <Text key={index} style={[styles.body, styles.emphasis]}>{`${text}${separator}`}</Text>;
      if (kind === 'code') return <Text key={index} style={[styles.code, { color: colors.text }]}>{`${text}${separator}`}</Text>;
      if (kind === 'a' || kind === 'clink') return <Text key={index} accessibilityRole="link"
        onPress={() => onOpenLink?.(kind === 'clink' ? copy[url] : url, text)}
        style={[styles.body, styles.link, { color: colors.accent }]}>{`${text}${separator}`}</Text>;
      return <Text key={index} style={[styles.body, { color: colors.textSecondary }]}>{`${text}${separator}`}</Text>;
    })}
  </Text>;
}

function Parts({ parts, copy, colors, buttonPalette, labels, copyState, copyKey, onCopy, onOpenLink }) {
  const segments = [];
  let inline = [];
  function flush() {
    if (!inline.length) return;
    segments.push({ kind: 'text', parts: inline });
    inline = [];
  }
  parts.forEach((part, index) => {
    if (part[0] === 'copy') {
      flush();
      segments.push({ kind: 'copy', key: part[1], index });
    } else if (part[0] === 'pre') {
      flush();
      segments.push({ kind: 'pre', text: part[1], index });
    } else {
      inline.push(part);
    }
  });
  flush();
  return <View style={styles.partGroup}>
    {segments.map(segment => {
      if (segment.kind === 'copy') return <CopyValue key={`copy-${segment.index}`}
        value={copy[segment.key] || ''} label={segment.key} colors={colors} buttonPalette={buttonPalette}
        labels={labels} state={copyState[`${copyKey}:${segment.key}`]}
        onCopy={value => onCopy(value, `${copyKey}:${segment.key}`)} />;
      if (segment.kind === 'pre') return <PreBlock key={`pre-${segment.index}`} text={segment.text}
        colors={colors} buttonPalette={buttonPalette} labels={labels}
        state={copyState[`${copyKey}:pre-${segment.index}`]}
        onCopy={value => onCopy(value, `${copyKey}:pre-${segment.index}`)} />;
      return <InlineParts key={`text-${segment.index}`} parts={segment.parts} colors={colors}
        copy={copy} onOpenLink={onOpenLink} />;
    })}
  </View>;
}

function Steps({ steps = [], copy, colors, buttonPalette, labels, copyState, copyKey, onCopy, onOpenLink }) {
  return <View accessibilityRole="list" style={styles.steps}>
    {steps.map((step, index) => {
      const parts = Array.isArray(step) ? step : step.parts || [];
      return <View key={index} accessibilityRole="listitem" style={styles.step}>
        <Parts parts={parts} copy={copy} colors={colors} buttonPalette={buttonPalette}
          labels={labels} copyState={copyState} copyKey={`${copyKey}:${index}`}
          onCopy={onCopy} onOpenLink={onOpenLink} />
        {step.items ? <View style={styles.items}>{step.items.map((item, itemIndex) =>
          <View key={itemIndex} style={styles.itemRow}>
            <Text style={[styles.body, { color: colors.textMuted }]}>•</Text>
            <Parts parts={item} copy={copy} colors={colors} buttonPalette={buttonPalette}
              labels={labels} copyState={copyState} copyKey={`${copyKey}:${index}:${itemIndex}`}
              onCopy={onCopy} onOpenLink={onOpenLink} />
          </View>)}</View> : null}
      </View>;
    })}
  </View>;
}

/** Collapsible step list presented with the legacy disclosure styling. */
function Disclosure({ open, onToggle, label, colors }) {
  return <Pressable accessibilityRole="button" accessibilityState={{ expanded: open }}
    accessibilityLabel={label} onPress={onToggle} style={styles.summary}>
    <Text style={[styles.summaryMarker, { color: colors.accent }]}>{open ? '▼' : '▶'}</Text>
    <Text style={[styles.summaryText, { color: colors.accent }]}>{label}</Text>
  </Pressable>;
}

/**
 * Shared setup-guide presentation. Copy values, links and their transport are
 * supplied by the caller; the browser adapter keeps token-bearing URLs in the
 * server fallback and a native adapter owns clipboard access.
 *
 * Layout matches the legacy guide contract: a status/primary card, then a
 * separate collapsed "steps" card (one per method when a provider offers more
 * than one setup path). Non-collapsed guides stay in one card.
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
  const [openMap, setOpenMap] = useState({});
  const [copyState, setCopyState] = useState({});
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const text = { ...defaultLabels, ...labels };
  const cards = { ...colors, background: colors.surfaceStrong };
  const badge = guide.badge ? { ...badgePalette(colors, guide.badge.tone), background: colors.surfaceStrong } : cards;

  function toggle(key) {
    setOpenMap(current => ({ ...current, [key]: !current[key] }));
  }

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
    {guide.warning ? <Text accessibilityRole="alert" style={[styles.body, { color: colors.textSecondary }]}>
      <Text style={[styles.body, styles.bold, { color: colors.text }]}>{guide.warning.title}</Text>{' '}{guide.warning.text}
    </Text> : null}
    {guide.badge?.summary ? <View style={styles.statusRow}>
      {guide.badge.tooltip ? <Tooltip label={guide.badge.label} text={guide.badge.tooltip} palette={colors} /> : null}
      <Text style={[styles.small, { color: colors.textMuted }]}>{guide.badge.summary}</Text>
    </View> : null}
    {guide.primary ? <View style={styles.primary}>
      <Text style={[styles.label, { color: colors.textMuted }]}>{guide.primary.label}</Text>
      <CopyValue value={copy[guide.primary.key] || ''} label={guide.primary.label} colors={colors}
        buttonPalette={buttons} labels={text} state={copyState[`primary:${guide.primary.key}`]} boxed
        onCopy={value => copyValue(value, `primary:${guide.primary.key}`)} />
    </View> : null}
  </>;

  const steps = <Steps steps={guide.steps || []} copy={copy} colors={colors}
    buttonPalette={buttons} labels={text} copyState={copyState} copyKey="steps"
    onCopy={copyValue} onOpenLink={onOpenLink} />;

  if (guide.bare) {
    return <View style={styles.content}>
      {intro}
      {guide.heading ? <Text role="heading" aria-level={4} style={[styles.heading, { color: colors.text }]}>{guide.heading}</Text> : null}
      {steps}
    </View>;
  }

  if (guide.collapsed) {
    // Status and copy value first; steps live in their own card(s) below.
    return <View style={styles.stack}>
      <SettingsCard title={guide.title} badge={guide.badge?.label} palette={badge}>
        {intro}
      </SettingsCard>
      {guide.methods?.length ? <View style={styles.methods}>
        {guide.methods.map((method, index) => {
          const key = `method-${index}`;
          const expanded = Boolean(openMap[key]);
          return <View key={method.title} style={styles.methodColumn}>
            <SettingsCard title={method.title} palette={cards}>
              {method.description ? <Text style={[styles.body, { color: colors.textSecondary }]}>{method.description}</Text> : null}
              <Disclosure open={expanded} onToggle={() => toggle(key)}
                label={expanded ? text.hideSteps : text.showSteps} colors={colors} />
              {expanded ? <Steps steps={method.steps || []} copy={copy} colors={colors}
                buttonPalette={buttons} labels={text} copyState={copyState} copyKey={key}
                onCopy={copyValue} onOpenLink={onOpenLink} /> : null}
            </SettingsCard>
          </View>;
        })}
      </View> : <SettingsCard title={guide.heading} palette={cards}>
        <Disclosure open={Boolean(openMap.steps)} onToggle={() => toggle('steps')}
          label={openMap.steps ? text.hideSteps : text.showSteps} colors={colors} />
        {openMap.steps ? <Steps steps={guide.steps || []} copy={copy} colors={colors}
          buttonPalette={buttons} labels={text} copyState={copyState} copyKey="steps"
          onCopy={copyValue} onOpenLink={onOpenLink} /> : null}
      </SettingsCard>}
    </View>;
  }

  return <SettingsCard title={guide.title} badge={guide.badge?.label} palette={badge}>
    {intro}
    {guide.heading ? <Text role="heading" aria-level={4} style={[styles.heading, { color: colors.text }]}>{guide.heading}</Text> : null}
    {steps}
  </SettingsCard>;
}

const styles = StyleSheet.create({
  content: { gap: 12, minWidth: 0 },
  stack: { flexDirection: 'column', gap: 16, minWidth: 0 },
  body: { fontSize: 13, lineHeight: 19 },
  small: { fontSize: 12, lineHeight: 17, flexShrink: 1 },
  bold: { fontWeight: '700' },
  emphasis: { fontStyle: 'italic' },
  code: { fontFamily: 'Courier', fontSize: 12 },
  codeBlock: { flexGrow: 1, flexShrink: 1, flexBasis: 224, minWidth: 0, wordBreak: 'break-all', overflowWrap: 'anywhere' },
  link: { textDecorationLine: 'underline' },
  label: { fontSize: 12, fontWeight: '600', letterSpacing: 0.5, textTransform: 'uppercase' },
  primary: { gap: 4, minWidth: 0 },
  copyRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8, minWidth: 0 },
  preBlock: { alignSelf: 'stretch', alignItems: 'flex-start', gap: 8, marginTop: 8, minWidth: 0 },
  pre: { alignSelf: 'stretch', borderRadius: 8, maxHeight: 288, minWidth: 0 },
  preText: { padding: 12, fontFamily: 'Courier', fontSize: 12, lineHeight: 18 },
  statusRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 4, minWidth: 0 },
  partGroup: { gap: 4, flexShrink: 1, minWidth: 0 },
  items: { gap: 3 },
  itemRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 6 },
  heading: { fontSize: 16, fontWeight: '500', lineHeight: 24 },
  methods: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'stretch', gap: 16 },
  methodColumn: { flexGrow: 1, flexBasis: 320, minWidth: 0 },
  steps: { flexDirection: 'column', gap: 8, paddingLeft: 20, minWidth: 0 },
  step: { minWidth: 0 },
  summary: { flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'flex-start', paddingVertical: 4 },
  summaryMarker: { fontSize: 12 },
  summaryText: { fontSize: 14, fontWeight: '500' },
});
