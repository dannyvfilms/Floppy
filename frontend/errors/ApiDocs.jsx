import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Chip } from '../settings/Chip';
import { SettingsCard } from '../settings/SettingsCard';
import { Button } from '../ui/Button';
import { CopyBlock } from '../ui/CopyBlock';

const defaultLabels = {
  copy: 'Copy',
  copied: 'Copied',
  open: 'Open',
  start: 'Start with a task',
  firstRequest: 'First request',
  workflows: 'Core integration workflows',
  cheatSheet: 'Reference cheat sheet',
  statusCodes: 'Tracking status codes',
  mediaTypes: 'Media type slugs',
  glossary: 'Domain model',
  schemas: 'API schemas',
  footer: 'Floppy API reference.',
};

function cardPalette(palette) {
  return {
    text: palette.text,
    border: palette.border,
    background: palette.surface,
    badgeBorder: palette.border,
    badgeBackground: palette.surfaceStrong,
    badgeText: palette.textSecondary,
    badgeHover: palette.surfaceMuted,
    focusStyle: palette.focusStyle,
  };
}

function actionPalette(palette) {
  return {
    surface: {
      background: palette.surfaceStrong,
      pressed: palette.surfaceMuted,
      hovered: palette.surfaceMuted,
      text: palette.text,
      border: palette.border,
    },
    radius: 6,
    focusStyle: palette.focusStyle,
  };
}

export function ApiDocCommand({ caption, note, command, copyLabel = defaultLabels.copy,
  copiedLabel = defaultLabels.copied, onCopy, palette }) {
  return <View style={styles.command}>
    <Text style={[styles.itemTitle, { color: palette.text }]}>{caption}</Text>
    <CopyBlock text={command} note={note} copyLabel={copyLabel} copiedLabel={copiedLabel}
      onCopy={onCopy} palette={palette} />
  </View>;
}

export function ApiCheatSheet({ rows, palette }) {
  return <View style={styles.rows}>
    {rows.map(row => <View key={`${row.category}-${row.path}`} style={[styles.row, { borderColor: palette.border }]}>
      <View style={styles.rowHeading}>
        <Text style={[styles.rowCategory, { color: palette.textSecondary }]}>{row.category}</Text>
        <Text selectable style={[styles.rowPath, { color: palette.accent }]}>{row.path}</Text>
      </View>
      <Text style={[styles.rowCopy, { color: palette.textMuted }]}>{row.description}</Text>
    </View>)}
  </View>;
}

export function ApiGlossary({ terms, palette }) {
  return <View style={styles.rows}>
    {terms.map(term => <View key={term.term} style={[styles.row, { borderColor: palette.border }]}>
      <Text style={[styles.itemTitle, { color: palette.text }]}>{term.term}</Text>
      <Text style={[styles.rowCopy, { color: palette.textMuted }]}>{term.definition}</Text>
    </View>)}
  </View>;
}

export function ApiSchemaLinks({ entries, labels = {}, onOpen, palette }) {
  const copy = { ...defaultLabels, ...labels };
  const buttons = actionPalette(palette);
  return <View style={styles.rows}>
    {entries.map(entry => <View key={entry.title} style={[styles.row, { borderColor: palette.border }]}>
      <View style={styles.rowHeading}>
        <Text style={[styles.itemTitle, { color: palette.text }]}>{entry.title}</Text>
        <Chip label={entry.badge} palette={{
          badgeBorder: palette.border,
          badgeBackground: palette.surfaceStrong,
          badgeText: palette.textSecondary,
          badgeHover: palette.surfaceMuted,
        }} />
      </View>
      <Text style={[styles.rowCopy, { color: palette.textMuted }]}>{entry.description}</Text>
      <View style={styles.inlineAction}>
        <Button label={copy.open} tone="surface" onPress={() => onOpen?.(entry)}
          accessibilityLabel={`${copy.open} ${entry.title}`} palette={buttons} />
      </View>
    </View>)}
  </View>;
}

export function ApiDocs({ model, labels = {}, palette, onOpenLink, onCopy }) {
  const copy = { ...defaultLabels, ...labels };
  return <View style={styles.stack}>
    <SettingsCard title={copy.start} palette={cardPalette(palette)}>
      <Text style={[styles.body, { color: palette.textMuted }]}>{model.intro}</Text>
      <View style={styles.chipRow}>
        {model.tasks.map(task => <Chip key={task.label} label={task.label} pill
          accessibilityRole="link" accessibilityLabel={task.label}
          onPress={() => onOpenLink?.(task)}
          palette={{
            badgeBorder: palette.border,
            badgeBackground: palette.surfaceStrong,
            badgeText: palette.textSecondary,
            badgeHover: palette.surfaceMuted,
            focusStyle: palette.focusStyle,
          }} />)}
      </View>
    </SettingsCard>

    <SettingsCard title={copy.firstRequest} palette={cardPalette(palette)}>
      <Text style={[styles.body, { color: palette.textMuted }]}>{model.firstRequest.intro}</Text>
      {model.firstRequest.commands.map(item => <ApiDocCommand key={item.caption} {...item}
        copyLabel={copy.copy} copiedLabel={copy.copied} onCopy={onCopy} palette={palette} />)}
    </SettingsCard>

    <SettingsCard title={copy.workflows} palette={cardPalette(palette)}>
      <Text style={[styles.body, { color: palette.textMuted }]}>{model.workflows.intro}</Text>
      {model.workflows.commands.map(item => <ApiDocCommand key={item.caption} {...item}
        copyLabel={copy.copy} copiedLabel={copy.copied} onCopy={onCopy} palette={palette} />)}
    </SettingsCard>

    <SettingsCard title={copy.cheatSheet} palette={cardPalette(palette)}>
      <ApiCheatSheet rows={model.cheatSheet} palette={palette} />
    </SettingsCard>

    <SettingsCard title={copy.statusCodes} palette={cardPalette(palette)}>
      <View style={styles.chipRow}>
        {model.statusCodes.map(item => <Chip key={item} label={item} palette={{
          badgeBorder: palette.border,
          badgeBackground: palette.surfaceStrong,
          badgeText: palette.textSecondary,
          badgeHover: palette.surfaceMuted,
        }} />)}
      </View>
    </SettingsCard>

    <SettingsCard title={copy.mediaTypes} palette={cardPalette(palette)}>
      <View style={styles.chipRow}>
        {model.mediaTypes.map(item => <Chip key={item} label={item} palette={{
          badgeBorder: palette.border,
          badgeBackground: palette.surfaceStrong,
          badgeText: palette.textSecondary,
          badgeHover: palette.surfaceMuted,
        }} />)}
      </View>
    </SettingsCard>

    <SettingsCard title={copy.glossary} palette={cardPalette(palette)}>
      <Text style={[styles.body, { color: palette.textMuted }]}>{model.glossaryIntro}</Text>
      <ApiGlossary terms={model.glossary} palette={palette} />
    </SettingsCard>

    <SettingsCard title={copy.schemas} palette={cardPalette(palette)}>
      <Text style={[styles.body, { color: palette.textMuted }]}>{model.schemasIntro}</Text>
      <ApiSchemaLinks entries={model.schemas} labels={copy} onOpen={onOpenLink} palette={palette} />
    </SettingsCard>

    <Text style={[styles.footer, { color: palette.textMuted }]}>{model.footer || copy.footer}</Text>
  </View>;
}

const styles = StyleSheet.create({
  stack: { gap: 16 },
  body: { fontSize: 13, lineHeight: 20 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  command: { gap: 6 },
  itemTitle: { fontSize: 14, fontWeight: '600' },
  rows: { gap: 0 },
  row: { gap: 6, borderTopWidth: 1, paddingVertical: 12 },
  rowHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' },
  rowCategory: { fontSize: 13, fontWeight: '600' },
  rowPath: { fontSize: 12 },
  rowCopy: { fontSize: 12, lineHeight: 18 },
  inlineAction: { flexDirection: 'row' },
  footer: { fontSize: 12, lineHeight: 18 },
});
