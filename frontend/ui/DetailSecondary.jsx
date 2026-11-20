import React from 'react';
import { Image, Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { MarkdownPreview } from './MarkdownPreview';
import { CollectionExpandRow, CollectionGroup, CollectionRow } from './CollectionCopies';
import { Button } from './Button';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';
import { MediumExtras } from './People';
import { detailSecondaryOrder } from './detailSecondaryModel';

function Value({ value, palette, onOpenLink, onOpenPerson }) {
  const text = <Text style={[styles.factValue, styles.endText, { color: palette.textSecondary }]}>{value.text}</Text>;
  // Native apps open a person in their own screen; the browser follows the href.
  const open = value.identity && onOpenPerson ? () => onOpenPerson(value.identity)
    : value.href && onOpenLink ? () => onOpenLink(value.href, value.identity) : null;
  return open
    ? <Pressable accessibilityRole="link" accessibilityLabel={value.text} onPress={open}>{text}</Pressable> : text;
}

// A detail's leading icon, by its key; unknown keys get the info glyph.
const FACT_ICONS = [
  [/runtime|duration|length/, 'alarmClock'],
  [/date|air|release|publish|updated|year|season/, 'calendar'],
  [/language|country|countries|origin|locale|broadcast/, 'globe'],
  [/status/, 'pulse'],
  [/format|type|source/, 'disc'],
  [/episode|chapter|volume|page|player/, 'list'],
  [/author|people|creator|network/, 'edit'],
  [/budget|revenue|price/, 'dollar'],
];
function factIcon(key) {
  const name = String(key || '').toLowerCase();
  return actionIcons[(FACT_ICONS.find(([pattern]) => pattern.test(name)) || [null, 'info'])[1]];
}

// The server labels some facts in capitals (RUNTIME); rows read better in title case.
const factLabel = label => (label && label === label.toUpperCase()
  ? label.toLowerCase().replace(/\b\w/g, letter => letter.toUpperCase()) : label);

// Platform opens the Summary-style breakdown: each platform with how many of the viewer's other
// games are collected on it. The collected platform for this game leads the list.
function PlatformsRow({ names, collected, counts, palette }) {
  const all = [...new Set([...collected, ...names])];
  return <CollectionExpandRow icon={actionIcons.monitor} label="Platform" palette={palette}
    items={all.map(name => ({ key: name, label: name, count: counts[name] }))} />;
}

export function DetailMetadata({ facts = [], title = 'Details', emptyLabel = 'No details available',
  palette, onOpenLink, onOpenPerson, promoted = false, variant = 'native', collectedPlatforms = [], platformCounts = {}, children }) {
  const rows = promoted ? facts.filter(fact => !fact.promoted) : facts;
  if (promoted && !rows.length && !children) return null;
  return <View style={styles.stack}>
    {children}
    {rows.length || !promoted ? <CollectionGroup title={title} palette={palette} variant={variant}>
      {rows.length ? rows.map(fact => fact.key === 'platforms' && (fact.values || []).length
        ? <PlatformsRow key={fact.key} names={fact.values.map(value => value.text)} collected={collectedPlatforms} counts={platformCounts} palette={palette} />
        : <CollectionRow key={fact.key} icon={factIcon(fact.key)} label={factLabel(fact.label)}
        palette={palette} multiline>
        <View style={styles.factValues}>
          {(fact.values || []).map((value, index) => <Value key={`${fact.key}-${index}`} value={value}
            palette={palette} onOpenLink={onOpenLink} onOpenPerson={onOpenPerson} />)}
        </View>
      </CollectionRow>) : <CollectionRow key="empty" icon={actionIcons.info} label={emptyLabel} palette={palette} />}
    </CollectionGroup> : null}
  </View>;
}

export function DetailWatchProviders({ providers, region, title = 'Streaming', emptyLabel = 'No watch providers', palette, variant = 'native' }) {
  if (region === 'UNSET' || providers === null || providers === undefined) return null;
  return <CollectionGroup title={title} palette={palette} variant={variant}>
    <CollectionRow icon={actionIcons.play} label={providers.length ? '' : emptyLabel} palette={palette} multiline>
      <View style={styles.providers}>
        {providers.map((provider, index) => provider.image
          ? <Image key={provider.provider_id || provider.provider_name || index}
            source={{ uri: provider.image }} resizeMode="contain" accessibilityLabel={provider.provider_name || provider.name}
            style={styles.providerImage} />
          : <Text key={provider.provider_id || provider.provider_name || index}
            style={[styles.value, { color: palette.textSecondary }]}>{provider.provider_name || provider.name}</Text>)}
      </View>
    </CollectionRow>
  </CollectionGroup>;
}

// Native apps open a studio in their own screen (`onOpenStudio`); the browser follows the href.
export function DetailStudios({ studios = [], title = 'Studios', palette, onOpenLink, onOpenStudio, variant = 'native' }) {
  if (!studios.length) return null;
  return <CollectionGroup title={title} palette={palette} variant={variant}>
    {studios.slice(0, 12).map((studio, index) => <CollectionRow key={studio.studio_id || index} icon={actionIcons.building}
      image={studio.logo || undefined} label={studio.name || 'Unknown Studio'} palette={palette}
      onPress={onOpenStudio ? () => onOpenStudio(studio) : studio.href && onOpenLink ? () => onOpenLink(studio.href, studio) : undefined}
      chevron={!!(onOpenStudio || (studio.href && onOpenLink))} />)}
  </CollectionGroup>;
}

export function DetailPromotedFacts({ facts = [], palette }) {
  const { width } = useWindowDimensions();
  if (!facts.length) return null;
  return <View style={[styles.promoted, { borderBottomColor: palette.border }]}>
    {facts.map(fact => <View key={fact.key} style={[styles.promotedFact, width < 768 && styles.promotedCompact]}>
      <Text style={[styles.promotedLabel, { color: palette.textMuted }]}>{fact.label}</Text>
      <Text style={[styles.value, { color: palette.textSecondary }]}>{fact.value}</Text>
    </View>)}
  </View>;
}

export function DetailMediumExtras({ gameLengths, youtubeWatch, playedLabel, labels, palette, onOpenLink, variant = 'native' }) {
  return <MediumExtras gameLengths={gameLengths} youtubeWatch={youtubeWatch} playedLabel={playedLabel}
    labels={labels} palette={palette} onOpenSource={onOpenLink} variant={variant} />;
}

// Genre opens the Summary-style breakdown: each genre with how many of the viewer's other items carry it.
export function DetailGenres({ genres = [], title = 'Genres', palette, variant = 'native' }) {
  if (!genres.length) return null;
  return <CollectionGroup title={title} palette={palette} variant={variant}>
    <CollectionExpandRow key="genres" icon={actionIcons.tag} label="Genre" palette={palette}
      items={genres.map((genre, index) => ({ key: `${genre.label}-${index}`, label: genre.label, count: genre.count }))} />
  </CollectionGroup>;
}

export function DetailTrackingHistory({ entries = [], count = entries.length + 1, hasMore = false,
  title = 'Your History', repeatsLabel = 'Show Repeats', palette, onEdit, onOpenHistory, variant = 'native' }) {
  const [expanded, setExpanded] = React.useState(false);
  if (count < 2) return null;
  return <View style={styles.stack}>
    <CollectionGroup title={title} palette={palette} variant={variant}>
      <CollectionRow icon={actionIcons.repeat} label={`${repeatsLabel} (${Math.max(0, count - 1)})`} palette={palette}
        onPress={() => setExpanded(value => !value)}>
        <View style={expanded ? { transform: [{ rotate: '180deg' }] } : undefined}>
          <Icon spec={actionIcons.chevronDown} size={16} color={palette.textMuted} />
        </View>
      </CollectionRow>
    </CollectionGroup>
    {expanded ? entries.map(entry => <CollectionGroup key={entry.id} palette={palette} variant={variant}>
      <CollectionRow icon={actionIcons.star} label={entry.scoreLabel || 'Not rated'} palette={palette}
        onPress={entry.editable && onEdit ? () => onEdit(entry) : undefined} chevron={!!(entry.editable && onEdit)}
        accessibilityLabel={entry.editable && onEdit ? 'Edit tracking entry' : undefined} />
      {[[entry.statusLabel, actionIcons.pulse], [entry.progressLabel, actionIcons.list],
        [entry.startedLabel, actionIcons.calendar], [entry.finishedLabel, actionIcons.circleCheck]]
        .filter(([line]) => line).map(([line, icon]) => <CollectionRow key={line} icon={icon} label={line} palette={palette} />)}
      {entry.notes ? <View key="notes" style={styles.historyNotes}><MarkdownPreview markdown={entry.notes} palette={palette} /></View> : null}
    </CollectionGroup>) : null}
    {expanded && hasMore && onOpenHistory ? <Button label="View all history" tone="surface" palette={palette} onPress={onOpenHistory} /> : null}
  </View>;
}

/** Section slots keep requests, permissions and editable content in their adapters. */
export function DetailSecondary({ model = {}, sections = {}, layout = model.layout,
  palette, onOpenLink, onOpenPerson, onOpenStudio, promote = false, variant = 'native', collectedPlatforms = [] }) {
  const { width } = useWindowDimensions();
  const wide = width >= 768;
  const promoted = promote && width >= 600 && model.promoted?.length > 0;
  const providers = model.watchProviderRegion !== 'UNSET' && Array.isArray(model.watchProviders)
    ? <DetailWatchProviders providers={model.watchProviders} region={model.watchProviderRegion}
      title={model.labels?.streaming} emptyLabel={model.labels?.noWatchProviders} palette={palette} variant={variant} /> : null;
  const showDetails = !promoted || (model.facts || []).some(fact => !fact.promoted) || (wide && providers);
  const slots = {
    details: showDetails ? <DetailMetadata facts={model.facts} title={model.labels?.details} emptyLabel={model.labels?.noDetails}
      palette={palette} onOpenLink={onOpenLink} onOpenPerson={onOpenPerson} promoted={promoted} variant={variant} collectedPlatforms={collectedPlatforms} platformCounts={model.platformCounts}>{wide ? providers : null}</DetailMetadata> : null,
    genres: model.genres?.length && !(wide && promote && !model.publicView)
      ? <DetailGenres genres={model.genres} palette={palette} onOpenLink={onOpenLink} variant={variant} /> : null,
    studios: model.studios?.length ? <DetailStudios studios={model.studios} palette={palette} onOpenLink={onOpenLink} onOpenStudio={onOpenStudio} variant={variant} /> : null,
    // One Time card holds played, watched and time to beat; the youtube_watch slot folds into it.
    game_lengths: model.gameLengths || model.youtubeWatch || model.playedLabel
      ? <DetailMediumExtras gameLengths={model.gameLengths} youtubeWatch={model.youtubeWatch} playedLabel={model.playedLabel}
        palette={palette} onOpenLink={onOpenLink} variant={variant} /> : null,
    ...sections,
  };
  const available = Object.keys(slots).filter(key => slots[key]);
  const sidebar = detailSecondaryOrder(layout, available, 'sidebar');
  const content = detailSecondaryOrder(layout, available, 'content');
  const railSections = ['seasons', 'cast', 'crew', 'recommendations'];
  const rows = (keys, compact = false, gap = 32) => keys.map((key, index) => <View key={key}
    style={[
      compact ? (['genres', 'studios', 'collection'].includes(key) ? styles.compactSection : styles.fullSection) : undefined,
      railSections.includes(key) && railSections.includes(keys[index - 1]) ? { marginTop: 12 - gap } : undefined,
    ]}>{slots[key]}</View>);
  return <View style={styles.secondary}>
    {promoted && sidebar.includes('details') ? <DetailPromotedFacts facts={model.promoted} palette={palette} /> : null}
    <View style={[styles.columns, wide && styles.columnsWide]}>
      {!wide ? providers : null}
      {sidebar.length ? <View style={[styles.sidebar, wide && styles.sidebarWide,
        width >= 600 && !wide && styles.sidebarCompact]}>{rows(sidebar, width >= 600 && !wide, width >= 600 && !wide ? 16 : 24)}</View> : null}
      {content.length ? <View style={[styles.content, wide && styles.contentWide]}>{rows(content)}</View> : null}
    </View>
  </View>;
}

const styles = StyleSheet.create({
  secondary: { gap: 24, width: '100%' },
  columns: { gap: 24, minWidth: 0 },
  columnsWide: { flexDirection: 'row', gap: 40, alignItems: 'flex-start' },
  sidebar: { gap: 24, minWidth: 0 },
  sidebarWide: { width: '25%', maxWidth: 250, flexShrink: 0 },
  sidebarCompact: { flexDirection: 'row', flexWrap: 'wrap', gap: 16 },
  compactSection: { flexBasis: '30%', flexShrink: 1, minWidth: 0 },
  fullSection: { width: '100%' },
  content: { minWidth: 0, gap: 32 },
  contentWide: { flex: 1 },
  stack: { gap: 24, minWidth: 0 },
  factValues: { flexShrink: 1, alignItems: 'flex-end', gap: 2 },
  endText: { textAlign: 'right' },
  // Matches the grouped rows' trailing value size (CollectionRow).
  factValue: { fontSize: 16, lineHeight: 22 },
  historyNotes: { paddingVertical: 12 },
  value: { fontSize: 14, lineHeight: 20 },
  providers: { flex: 1, flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'flex-end', gap: 8 },
  providerImage: { width: 40, height: 40, borderRadius: 6 },
  promoted: { flexDirection: 'row', flexWrap: 'wrap', columnGap: 32, rowGap: 16,
    paddingBottom: 20, marginBottom: 4, borderBottomWidth: 1 },
  promotedFact: { maxWidth: 384, minWidth: 0, gap: 6 },
  promotedCompact: { flexBasis: '21%', flexGrow: 1 },
  promotedLabel: { fontSize: 14, lineHeight: 20, fontWeight: '600' },
});
