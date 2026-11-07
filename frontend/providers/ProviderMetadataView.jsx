import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import { FeatureList, MediaIcon } from '../ui/controls/FeatureList';
import { SelectField } from '../ui/SelectField';
import { TextField } from '../ui/TextField';
import { Chip } from '../settings/Chip';
import { SettingsCard } from '../settings/SettingsCard';

const DEFAULT_PALETTE = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentText: '#ffffff',
  danger: '#ef4444',
  success: '#10b981',
  warning: '#f59e0b',
  badgeBorder: '#3f3f46',
  badgeBackground: '#3f3f46',
  badgeText: '#d4d4d8',
  badgeHover: '#52525b',
  infoBorder: 'rgba(99, 102, 241, 0.3)',
  infoBackground: 'rgba(99, 102, 241, 0.1)',
  infoBadgeBorder: 'rgba(99, 102, 241, 0.3)',
  infoBadgeBackground: 'rgba(99, 102, 241, 0.1)',
  infoBadgeText: '#c7d2fe',
  warningBorder: 'rgba(245, 158, 11, 0.3)',
  warningBackground: 'rgba(245, 158, 11, 0.1)',
  warningBadgeBorder: 'rgba(245, 158, 11, 0.4)',
  warningBadgeBackground: 'rgba(245, 158, 11, 0.2)',
  warningBadgeText: '#fde68a',
  radius: 18,
};

const DEFAULT_BUTTON_PALETTE = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  'danger-solid': { background: '#dc2626', pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  radius: 18,
};

function tonePalette(colors, tone) {
  if (tone === 'info') {
    return {
      ...colors,
      border: colors.infoBorder,
      background: colors.infoBackground,
      badgeBorder: colors.infoBadgeBorder,
      badgeBackground: colors.infoBadgeBackground,
      badgeText: colors.infoBadgeText,
    };
  }
  if (tone === 'warning') {
    return {
      ...colors,
      border: colors.warningBorder,
      background: colors.warningBackground,
      badgeBorder: colors.warningBadgeBorder,
      badgeBackground: colors.warningBadgeBackground,
      badgeText: colors.warningBadgeText,
    };
  }
  return colors;
}

function chipPalette(colors, tone) {
  if (tone === 'success') {
    return { ...colors, badgeBorder: colors.success, badgeBackground: 'rgba(16, 185, 129, 0.15)', badgeText: '#a7f3d0' };
  }
  if (tone === 'warning') {
    return { ...colors, badgeBorder: colors.warning, badgeBackground: 'rgba(245, 158, 11, 0.15)', badgeText: '#fde68a' };
  }
  if (tone === 'info') {
    return { ...colors, badgeBorder: colors.accent, badgeBackground: 'rgba(99, 102, 241, 0.15)', badgeText: '#c7d2fe' };
  }
  return colors;
}

function SourceSettings({
  source,
  colors,
  buttons,
  t,
  renderIcon,
  onSaveSource,
  onMove,
  onOpenLink,
}) {
  const [value, setValue] = useState(source.current);
  const [animeMode, setAnimeMode] = useState(source.animeMode);
  const [open, setOpen] = useState(false);
  const configured = source.choices.find(choice => choice.value === value)?.configured;
  const detailsId = `metadata-source-details-${source.key}`;

  return <View testID="metadata-source-row" style={[styles.sourceRow, { borderColor: colors.border, backgroundColor: colors.surface }]}>
    <View style={styles.sourceHeader}>
      <View style={styles.sourceName}>
        <MediaIcon type={source.key} palette={colors} renderIcon={renderIcon} />
        <Text role="heading" aria-level={4} style={[styles.sourceTitle, { color: colors.text }]}>
          {source.title}
        </Text>
      </View>
      <View style={styles.sourceActions}>
        <Chip label={source.currentLabel} pill palette={chipPalette(colors, 'warning')} />
        <Button label={t(open ? 'Close' : 'Configure')} tone="surface"
          accessibilityLabel={`${t(open ? 'Close' : 'Configure')} ${source.title}`}
          onPress={() => setOpen(current => !current)} palette={buttons} />
      </View>
    </View>

    {open ? <View nativeID={detailsId} style={styles.details}>
      {source.action ? <>
        <Text style={[styles.copy, { color: colors.textSecondary }]}>
          {t('Used for new titles. Existing entries keep their provider until you move them.')}
        </Text>
        <SelectField id={`metadata-source-${source.key}`} name="source"
          label={t('Provider for new titles')} value={value} disabled={!source.editable}
          onChange={event => setValue(event.target.value)} palette={colors}
          options={source.choices.map(choice => ({
            value: choice.value,
            label: choice.label,
            disabled: !choice.configured,
          }))} />
        {source.animeMode !== null ? <SelectField id="metadata-anime-mode" name="anime_library_mode"
          label={t('Anime Library')} value={animeMode} disabled={!source.editable}
          onChange={event => setAnimeMode(event.target.value)} options={source.animeModes}
          palette={colors} /> : null}
        {source.editable ? <Button label={t('Save')} disabled={!configured}
          onPress={() => onSaveSource?.({
            key: source.key,
            source: value,
            ...(source.animeMode !== null ? { animeMode } : {}),
            action: source.action,
          })} palette={buttons} /> : null}
      </> : <>
        <Text style={[styles.copy, { color: colors.textSecondary }]}>
          {t('Default for new titles')}: {source.currentLabel}
        </Text>
        <Text style={[styles.copy, { color: colors.textMuted }]}>
          {t('The default cannot be changed. Imported titles keep their original source.')}
        </Text>
      </>}

      <View testID="metadata-options" style={styles.optionList}>
        {source.choices.map(choice => <View key={choice.value} style={[styles.optionRow, { borderColor: colors.border }]}>
          <Text style={[styles.optionLabel, { color: colors.textSecondary }]}>{choice.label}</Text>
          {!choice.configured && choice.connectionUrl
            ? <Chip label={t('Not configured')} link={Boolean(onOpenLink)}
              onPress={onOpenLink ? () => onOpenLink(choice.connectionUrl) : undefined}
              palette={colors} />
            : <Chip label={t(!choice.configured
              ? 'Not configured'
              : choice.value === source.current
                ? 'Default'
                : choice.imported
                  ? 'Imported items'
                  : source.action ? 'Ready' : 'Available')}
              palette={chipPalette(colors, choice.configured && choice.value === source.current ? 'info' : 'neutral')} />}
        </View>)}
      </View>
    </View> : null}

    {source.existingCount > 0 ? <View style={[styles.existing, { borderColor: colors.border }]}>
      <Text style={[styles.copy, { color: colors.textSecondary }]}>
        {t('Existing entries on another provider or format')}: {source.existingCount}
      </Text>
      <Text style={[styles.copy, { color: colors.textMuted }]}>
        {t(source.key === 'tv'
          ? 'Moving preserves history when supported; entries that cannot be moved safely are left unchanged.'
          : 'Converting rebuilds entries. Moving to MyAnimeList drops per-episode history; unsafe conversions are left unchanged.')}
      </Text>
      {source.moveAction ? <Button
        label={t(source.key === 'tv' ? 'Move existing shows' : 'Convert existing anime')}
        tone="surface"
        onPress={() => onMove?.({ key: source.key, action: source.moveAction })}
        palette={buttons} /> : null}
    </View> : null}
  </View>;
}

/**
 * Universal provider Metadata tab.
 *
 * `model` is the provider page model and `model.metadata` carries the same
 * status, contributions, proxy and library-source entries the web view reads.
 * Transport stays with the adapter:
 *
 *   onSaveProxy(url) -> save (or, when blank, remove) the TMDB proxy
 *   onSaveSource({ key, source, animeMode?, action }) -> save a new-title provider;
 *     animeMode is present only for libraries that expose that choice
 *   onMove({ key, action }) -> move or convert existing entries
 *   onOpenLink(url) -> open an unconfigured provider's Connection page
 *
 * `renderIcon({ type, size, color, label })` lets a platform adapter replace the
 * fallback media glyph. Entered proxy values never come from the model.
 */
export function ProviderMetadataView({
  model = {},
  labels,
  palette = {},
  buttonPalette = {},
  renderIcon,
  onSaveProxy,
  onSaveSource,
  onMove,
  onOpenLink,
  onOpenUrl,
}) {
  const [proxyUrl, setProxyUrl] = useState('');
  const metadata = model.metadata;
  if (!metadata) return null;

  const colors = { ...DEFAULT_PALETTE, ...(palette || {}) };
  const buttons = { ...DEFAULT_BUTTON_PALETTE, ...(buttonPalette || {}) };
  const text = { ...(model.labels || {}), ...(labels || {}) };
  const t = key => text[key] ?? key;
  const status = metadata.status || {};
  const sources = metadata.sources || [];
  const openLink = onOpenLink || onOpenUrl;
  const sourceTone = status.active ? 'info' : 'neutral';

  return <View testID="provider-metadata" style={styles.page}>
    <Text role="heading" aria-level={3} style={[styles.heading, { color: colors.text }]}>
      {t('Metadata settings')}
    </Text>

    <View style={styles.cardGrid}>
      <View style={styles.cardColumn}><SettingsCard title={t('Metadata sources')}
        badge={t(status.active ? 'Active' : 'Inactive')}
        palette={tonePalette(colors, sourceTone)}>
        <Text style={[styles.copy, { color: colors.textSecondary }]}>{status.summary}</Text>
        {metadata.imported ? <Text style={[styles.copy, { color: colors.textMuted }]}>
          {t('This provider supplies metadata for its imported items; library defaults apply to new searches.')}
        </Text> : null}
        <FeatureList items={metadata.contributions} palette={colors} />
      </SettingsCard></View>

      <View style={styles.cardColumn}><SettingsCard title={t('Provider settings')} palette={colors}>
        {metadata.proxy ? <>
          <View style={styles.headingRow}>
            <Text role="heading" aria-level={4} style={[styles.subheading, { color: colors.text }]}>
              {t('TMDB Proxy')}
            </Text>
            <Chip label={t(metadata.proxy.configured ? 'Configured' : 'Not configured')}
              palette={chipPalette(colors, metadata.proxy.configured ? 'info' : 'neutral')} />
          </View>
          <Text style={[styles.copy, { color: colors.textSecondary }]}>
            {t('Route TMDB requests through an HTTP or SOCKS5 proxy. Leave blank and save to remove it.')}
          </Text>
          <View style={styles.form}>
            <TextField id="tmdb-proxy-url" name="tmdb_proxy_url" label={t('Proxy URL')}
              placeholder="socks5://user:pass@host:port" autoComplete="off"
              value={proxyUrl} onChangeText={setProxyUrl} palette={colors} />
            <Button label={t('Save')} onPress={() => onSaveProxy?.(proxyUrl)} palette={buttons} />
          </View>
        </> : <Text style={[styles.copy, { color: colors.textMuted }]}>
          {t('This provider has no additional settings.')}
        </Text>}
      </SettingsCard></View>
    </View>

    {sources.length > 0 ? <View style={styles.librarySection}>
      <Text role="heading" aria-level={3} style={[styles.heading, { color: colors.text }]}>
        {t('Library sources')}
      </Text>
      <Text style={[styles.copy, { color: colors.textSecondary }]}>
        {t('Choose where new titles come from. Existing titles keep their original provider.')}
      </Text>
      <View style={styles.sourceList}>
        {sources.map(source => <SourceSettings key={source.key} source={source}
          colors={colors} buttons={buttons} t={t} renderIcon={renderIcon}
          onSaveSource={onSaveSource} onMove={onMove} onOpenLink={openLink} />)}
      </View>
    </View> : null}
  </View>;
}

const styles = StyleSheet.create({
  page: { gap: 24, minWidth: 0 },
  cardGrid: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'flex-start', gap: 12 },
  cardColumn: { flexGrow: 1, flexBasis: 260, minWidth: 0 },
  heading: { fontSize: 20, lineHeight: 28, fontWeight: '600' },
  subheading: { fontSize: 16, lineHeight: 24, fontWeight: '600', flexShrink: 1 },
  headingRow: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    flexWrap: 'wrap', gap: 8,
  },
  copy: { fontSize: 14, lineHeight: 21 },
  form: { gap: 12 },
  librarySection: { gap: 12, minWidth: 0 },
  sourceList: { gap: 12, minWidth: 0 },
  sourceRow: { borderWidth: 1, borderRadius: 8, padding: 16, gap: 12, minWidth: 0 },
  sourceHeader: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    flexWrap: 'wrap', gap: 12, minWidth: 0,
  },
  sourceName: { flexDirection: 'row', alignItems: 'center', gap: 8, minWidth: 0, flexShrink: 1 },
  sourceTitle: { fontSize: 16, lineHeight: 24, fontWeight: '600', flexShrink: 1 },
  sourceActions: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end',
    flexWrap: 'wrap', gap: 8, marginLeft: 'auto', minWidth: 0,
  },
  details: { gap: 12, minWidth: 0 },
  optionList: { gap: 4, minWidth: 0 },
  optionRow: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    flexWrap: 'wrap', gap: 8, borderTopWidth: 1, paddingVertical: 6, minWidth: 0,
  },
  optionLabel: { fontSize: 13, lineHeight: 19, flexShrink: 1 },
  existing: { gap: 8, borderTopWidth: 1, paddingTop: 12, minWidth: 0 },
});
