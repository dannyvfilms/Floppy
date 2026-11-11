import React from 'react';
import { ActivityIndicator, Image, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { Icon } from './Icon';
import { Modal } from './Modal';
import { actionIcons } from './actionIcons';

// Shared presentation for the detail page's own controls: the track action bar,
// provider score chips and series graph, the collection and notes blocks, the
// related grid, comic issue cards and anime episode cards. Props only: the screen
// adapter owns every request, dialog and permission, and passes colors in `palette`.

function QuickButton({ item, palette }) {
  return <Pressable accessibilityRole="button" accessibilityLabel={item.label} onPress={item.onPress}
    disabled={item.disabled}
    style={({ pressed }) => [styles.quick, {
      backgroundColor: pressed ? palette.surfaceMuted : palette.surfaceStrong,
      borderColor: item.active ? palette.accent : palette.border,
      opacity: item.disabled ? 0.5 : 1,
    }]}>
    <Icon spec={actionIcons[item.icon]} size={20} color={item.active ? palette.accent : palette.text} />
  </Pressable>;
}

export function DetailActionBar({ primary, edit, quick = [], palette }) {
  return <View style={styles.actionBar}>
    {primary ? <View style={styles.primaryRow}>
      <Pressable accessibilityRole="button" onPress={primary.onPress} disabled={primary.disabled}
        style={({ pressed }) => [styles.primary, edit ? styles.primaryJoined : null, {
          backgroundColor: pressed ? palette.accent : palette.accentStrong,
          opacity: primary.disabled ? 0.6 : 1,
        }]}>
        {primary.icon ? <Icon spec={actionIcons[primary.icon]} size={20} color={palette.accentContrast} /> : null}
        <Text style={[styles.primaryText, { color: palette.accentContrast }]}>{primary.label}</Text>
      </Pressable>
      {edit ? <Pressable accessibilityRole="button" accessibilityLabel={edit.label} onPress={edit.onPress}
        style={({ pressed }) => [styles.edit, {
          backgroundColor: pressed ? palette.accent : palette.accentStrong,
          borderLeftColor: palette.accent,
        }]}>
        <Icon spec={actionIcons[edit.icon || 'edit']} size={20} color={palette.accentContrast} />
      </Pressable> : null}
    </View> : null}
    {quick.length ? <View style={styles.quickRow}>
      {quick.map(item => <QuickButton key={item.key} item={item} palette={palette} />)}
    </View> : null}
  </View>;
}

function ScoreChip({ chip, palette, onPress, compact }) {
  const accent = (palette.scoreAccents || {})[chip.key] || (palette.scoreAccents || {}).provider;
  const count = chip.count ? String(chip.count) : '';
  if (compact) {
    const pillStyle = [styles.scorePill, { backgroundColor: accent ? accent.fill : palette.surface, borderColor: accent ? accent.border : palette.border }];
    const pillBody = <>
      <View style={[styles.scorePillLogo, accent ? { borderColor: accent.border, backgroundColor: accent.fill } : null]}>
        {chip.logo ? <Image source={{ uri: chip.logo }} resizeMode="contain" style={styles.scoreLogoImage} accessible={false} />
          : <Text style={[styles.scoreBrand, { color: palette.text }]}>{String(chip.label).slice(0, 4).toUpperCase()}</Text>}
      </View>
      <Text style={[styles.scorePillText, { color: palette.text }]}>{chip.value}</Text>
      {count ? <Text style={[styles.scorePillText, { color: palette.textMuted }]}>{`| ${count}`}</Text> : null}
    </>;
    if (!onPress) return <View accessible accessibilityLabel={`${chip.label} ${chip.value}`} style={pillStyle}>{pillBody}</View>;
    return <Pressable accessibilityRole="button" accessibilityLabel={`${chip.label} ${chip.value}`} onPress={onPress} style={pillStyle}>{pillBody}</Pressable>;
  }
  const body = <>
    <View style={[styles.scoreLogo, accent ? { borderColor: accent.border, backgroundColor: accent.fill } : null]}>
      {chip.logo ? <Image source={{ uri: chip.logo }} resizeMode="contain" style={styles.scoreLogoImage} accessible={false} />
        : <Text style={[styles.scoreBrand, { color: palette.text }]}>{String(chip.label).slice(0, 4).toUpperCase()}</Text>}
    </View>
    <View style={styles.scoreText}>
      <Text style={[styles.scoreValue, { color: palette.text }]}>{chip.value}</Text>
      {count ? <Text numberOfLines={1} style={[styles.scoreLabel, { color: palette.textSecondary }]}>{count}</Text> : null}
    </View>
  </>;
  const style = [styles.scoreChip, {
    backgroundColor: accent ? accent.fill : palette.surface,
    borderColor: accent ? accent.border : palette.border,
  }];
  if (!onPress) return <View accessible accessibilityLabel={`${chip.label} ${chip.value}`} style={style}>{body}</View>;
  return <Pressable accessibilityRole="button" accessibilityLabel={`${chip.label} ${chip.value}`} onPress={onPress} style={style}>{body}</Pressable>;
}

export function DetailScoreRow({ children, chips = [], progressSlot, palette, graphs, graphTitle = 'Series Graph', onOpenLink, ratingWide = false, compact = false }) {
  const { width } = useWindowDimensions();
  const [graphKey, setGraphKey] = React.useState('');
  if (!children && !chips.length && !progressSlot) return null;
  // The web row scrolls sideways: progress card, then each source's card, then the viewer's rating.
  return <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.scoreScroll}>
    {progressSlot ? <View style={{ width: Math.max(240, width - 34) }}>{progressSlot}</View> : null}
    {chips.map(chip => <ScoreChip key={chip.key} chip={chip} palette={palette} compact={compact}
      onPress={chip.graph && graphs?.[chip.graph] ? () => setGraphKey(chip.graph)
        : (chip.url && onOpenLink ? () => onOpenLink(chip.url) : null)} />)}
    {children ? <View style={{ width: ratingWide ? 340 : 166 }}>{children}</View> : null}
    <DetailSeriesGraph graph={graphs?.[graphKey]} title={graphTitle} palette={palette} onClose={() => setGraphKey('')} />
  </ScrollView>;
}

/** The web "View series graph" popover: one coloured cell per episode (or season) rating. */
export function DetailSeriesGraph({ graph, title, palette, onClose }) {
  if (!graph) return null;
  const columns = graph.seasons || [];
  return <Modal transparent animationType="fade" visible onRequestClose={onClose}>
    <View style={[styles.graphScrim, { backgroundColor: palette.overlay }]}>
      <View style={[styles.graphCard, { backgroundColor: palette.surface, borderColor: palette.border }]}>
        <View style={styles.blockHeader}>
          <Text accessibilityRole="header" style={[styles.blockTitle, { color: palette.text }]}>{graph.title || title}</Text>
          <Pressable accessibilityRole="button" accessibilityLabel="Close" onPress={onClose} style={styles.roundButton}>
            <Icon spec={actionIcons.close || actionIcons.x} size={18} color={palette.textMuted} />
          </Pressable>
        </View>
        <ScrollView horizontal><ScrollView style={styles.graphScroll}>
          <View style={styles.graphRow}>
            <Text style={[styles.graphCorner, { color: palette.textMuted }]}>{graph.row_label || ''}</Text>
            {columns.map(column => <Text key={column.label} style={[styles.graphHead, { color: palette.textMuted }]}>{column.label}</Text>)}
          </View>
          {(graph.episode_rows || []).map(row => <View key={row.ep} style={styles.graphRow}>
            <Text style={[styles.graphCorner, { color: palette.textMuted }]}>{row.ep}</Text>
            {row.cells.map((cell, index) => <View key={index} accessible
              accessibilityLabel={cell.score == null ? 'No rating' : `${cell.score}`}
              style={[styles.graphCell, { backgroundColor: cell.score == null ? palette.surfaceMuted : cell.color }]}>
              <Text style={[styles.graphCellText, { color: palette.accentContrast }]}>{cell.score == null ? '' : String(cell.score)}</Text>
            </View>)}
          </View>)}
        </ScrollView></ScrollView>
        <View style={styles.graphLegend}>
          {(graph.legend || []).map(entry => <View key={entry.label} style={styles.graphLegendItem}>
            <View style={[styles.graphSwatch, { backgroundColor: entry.color }]} />
            <Text style={[styles.scoreLabel, { color: palette.textMuted }]}>{entry.label}</Text>
          </View>)}
        </View>
      </View>
    </View>
  </Modal>;
}

const PHONE_HERO_MAX = 768;

export function DetailBlock({ title, action, palette, children }) {
  return <View style={styles.block}>
    <View style={styles.blockHeader}>
      <Text accessibilityRole="header" style={[styles.blockTitle, { color: palette.text }]}>{title}</Text>
      {action ? <Pressable accessibilityRole="button" accessibilityLabel={action.label} onPress={action.onPress}
        style={({ pressed }) => [styles.roundButton, {
          backgroundColor: pressed ? palette.accent : palette.accentStrong,
        }]}>
        <Icon spec={actionIcons[action.icon || 'plus']} size={20} color={palette.accentContrast} />
      </Pressable> : null}
    </View>
    {children}
  </View>;
}

export function DetailEmpty({ text, palette }) {
  return <Text style={[styles.empty, { color: palette.textMuted }]}>{text}</Text>;
}

export function DetailLoading({ text, palette }) {
  return <View accessibilityLiveRegion="polite" style={styles.loading}>
    <ActivityIndicator color={palette.accent} />
    <Text style={[styles.empty, { color: palette.textMuted }]}>{text}</Text>
  </View>;
}

export function DetailNotesBlock({ title, notes, editLabel, onEdit, palette }) {
  if (!notes.length) return null;
  return <View style={styles.block}>
    <Text accessibilityRole="header" style={[styles.blockTitle, { color: palette.text }]}>{title}</Text>
    {notes.map(note => <View key={note.id} style={styles.noteGroup}>
      <Text style={[styles.noteDate, { color: palette.textMuted }]}>{note.date}</Text>
      <View style={[styles.note, { backgroundColor: palette.surface, borderColor: palette.border }]}>
        <Text style={[styles.noteText, { color: palette.textSecondary }]}>{note.text}</Text>
        {onEdit ? <Pressable accessibilityRole="button" accessibilityLabel={editLabel}
          onPress={() => onEdit(note)} style={styles.noteEdit}>
          <Icon spec={actionIcons.edit} size={16} color={palette.textSecondary} />
        </Pressable> : null}
      </View>
    </View>)}
  </View>;
}

export function DetailCollectionBlock({ counts = [], entries, empty, palette }) {
  return <View style={[styles.card, { backgroundColor: palette.surface }]}>
    {counts.map(count => <View key={count.label} style={styles.infoCell}>
      <Text style={[styles.infoLabel, { color: palette.textMuted }]}>{count.label}</Text>
      <Text style={[styles.infoValue, { color: palette.textSecondary }]}>{count.value}</Text>
    </View>)}
    {entries.map(entry => <View key={entry.id} style={styles.infoCell}>
      <Text style={[styles.infoLabel, { color: palette.textMuted }]}>{entry.title}</Text>
      {entry.date ? <Text style={[styles.infoValue, { color: palette.textSecondary }]}>{entry.date}</Text> : null}
    </View>)}
    {!counts.length && !entries.length
      ? <Text style={[styles.infoValue, { color: palette.textSecondary }]}>{empty}</Text> : null}
  </View>;
}

const EPISODE_ACTION_ICONS = { watch: 'eyeClosed', unwatch: 'eye', collection: 'cube', lists: 'listAdd', history: 'history' };

function EpisodeCard({ episode, palette, labels, renderRating, onOpen, onAction, onRate, nativeAnime = false, list = false }) {
  const [rating, setRating] = React.useState(false);
  const [expanded, setExpanded] = React.useState(false);
  const actions = episode.actions || [];
  const byKey = key => actions.find(action => action.key === key);
  const toggle = byKey('watch') || byKey('unwatch');
  const collection = byKey('collection');
  const pill = [styles.episodePill, { backgroundColor: palette.surfaceStrong }];
  const circle = (key, color) => {
    const action = byKey(key);
    if (!action) return null;
    return <Pressable key={key} accessibilityRole="button" accessibilityLabel={action.label} disabled={action.disabled}
      onPress={() => onAction?.(action.key, episode)}
      style={[styles.episodeAction, { backgroundColor: color, opacity: action.disabled ? 0.5 : 1 }]}>
      <Icon spec={actionIcons[EPISODE_ACTION_ICONS[key]]} size={16} color={palette.accentContrast} />
    </Pressable>;
  };
  if (nativeAnime && list) return <View style={[styles.animeEpisodeRow, { backgroundColor: palette.surface }]}>
    <Text style={[styles.activity, { color: palette.textMuted, width: 36 }]}>{episode.code}</Text>
    <Pressable accessibilityRole="link" onPress={() => onOpen?.(episode)} style={{ flex: 1 }}>
      <Text numberOfLines={1} style={[styles.linkText, { color: palette.text }]}>{episode.title}</Text>
      <Text numberOfLines={1} style={[styles.activity, { color: palette.textMuted }]}>{episode.subtitle}</Text>
    </Pressable>
    <Pressable accessibilityRole="button" accessibilityLabel="Track Episode" onPress={() => onAction?.('track', episode)} style={pill}>
      <Text style={[styles.linkText, { color: palette.text }]}>{episode.watched ? 'Watched' : 'Unwatched'}</Text>
    </Pressable>
  </View>;
  return <View style={[styles.episodeCard, { backgroundColor: palette.surface }]}>
    {nativeAnime ? <View style={[styles.episodeBanner, { backgroundColor: palette.surfaceStrong }]}>
      <Pressable accessibilityRole="link" accessibilityLabel={episode.title} onPress={() => onOpen?.(episode)}
        style={StyleSheet.absoluteFill}>
        {episode.image?.src ? <Image source={{ uri: episode.image.src }} resizeMode="cover" style={StyleSheet.absoluteFill}
          accessible={false} /> : null}
        {[40, 52, 64, 76, 88].map(top => <View key={top} pointerEvents="none"
          style={[styles.episodeShade, { backgroundColor: palette.background, top: `${top}%` }]} />)}
      </Pressable>
      <View style={styles.episodeBannerText}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <Pressable accessibilityRole="link" onPress={() => onOpen?.(episode)} style={{ flexShrink: 1 }}>
            <Text numberOfLines={1} style={[styles.episodeTitle, { color: palette.text }]}>{episode.title}</Text>
          </Pressable>
          {episode.canRate ? <Pressable accessibilityRole="button" accessibilityLabel={labels.rate}
            accessibilityState={{ expanded: rating }} onPress={() => setRating(value => !value)}
            style={{ padding: 4 }}>
            <Icon spec={actionIcons.star} size={14} color={palette.warning} />
          </Pressable> : null}
        </View>
        {episode.subtitle ? <Text style={[styles.activity, styles.episodeSubtitle, { color: palette.textSecondary }]}>{episode.subtitle}</Text> : null}
      </View>
    </View> : <Pressable accessibilityRole="link" accessibilityLabel={episode.title} onPress={() => onOpen?.(episode)}
      style={[styles.episodeBanner, { backgroundColor: palette.surfaceStrong }]}>
      {episode.image?.src ? <Image source={{ uri: episode.image.src }} resizeMode="cover" style={StyleSheet.absoluteFill}
        accessible={false} /> : null}
      {[40, 52, 64, 76, 88].map(top => <View key={top} pointerEvents="none"
        style={[styles.episodeShade, { backgroundColor: palette.background, top: `${top}%` }]} />)}
      <View style={styles.episodeBannerText}>
        <Text numberOfLines={2} style={[styles.episodeTitle, { color: palette.text }]}>{episode.title}</Text>
        {episode.subtitle ? <Text style={[styles.activity, styles.episodeSubtitle, { color: palette.textSecondary }]}>{episode.subtitle}</Text> : null}
      </View>
    </Pressable>}
    {toggle && !nativeAnime ? <Pressable accessibilityRole="button" accessibilityLabel={toggle.label} disabled={toggle.disabled}
      onPress={() => onAction?.(toggle.key, episode)}
      style={[styles.episodeEye, { backgroundColor: palette.background, opacity: toggle.disabled ? 0.5 : 0.85 }]}>
      <Icon spec={actionIcons[EPISODE_ACTION_ICONS[toggle.key]]} size={16} color={toggle.key === 'unwatch' ? palette.accent : palette.text} />
    </Pressable> : null}
    <View style={styles.episodeBody}>
      {rating && episode.canRate && renderRating ? <View style={[styles.note, { backgroundColor: palette.surfaceStrong, borderColor: palette.border }]}>
        {renderRating({
          value: episode.score,
          label: labels.rate,
          scaleMax: 10,
          palette: palette.rating,
          onSelect: score => { setRating(false); onRate?.(episode, score); },
        })}
      </View> : null}
      {nativeAnime ? <View>
        <Text numberOfLines={nativeAnime && !expanded ? 3 : undefined} style={[styles.noteText, { color: palette.textSecondary }]}>{episode.overview}</Text>
        {nativeAnime && episode.overview?.length > 126 ? <Pressable accessibilityRole="button" onPress={() => setExpanded(value => !value)}>
          <Text style={{ color: palette.accent, fontSize: 13, fontWeight: '600' }}>{expanded ? 'Show less' : 'Read more'}</Text>
        </Pressable> : null}
      </View> : <Text style={[styles.noteText, { color: palette.textSecondary }]}>{episode.overview}</Text>}
      <View style={styles.episodeFooter}>
        {nativeAnime ? <Pressable accessibilityRole="button" accessibilityLabel="Track Episode" onPress={() => onAction?.('track', episode)} style={pill}>
          <Text style={[styles.linkText, { color: palette.text }]}>{episode.watched ? 'Watched' : 'Unwatched'}</Text>
        </Pressable> : <View style={pill}><Text style={[styles.linkText, { color: palette.text }]}>{episode.watched ? 'Watched' : 'Unwatched'}</Text></View>}
        {collection ? <Pressable accessibilityRole="button" accessibilityLabel={collection.label} onPress={() => onAction?.('collection', episode)}
          style={pill}><Text style={[styles.linkText, { color: palette.text }]}>{episode.collected ? 'Collected' : 'Uncollected'}</Text></Pressable> : null}
        {circle('lists', palette.success)}
        {circle('history', palette.warning)}
        {!nativeAnime && episode.canRate && (episode.watched || episode.score != null) ? <Pressable accessibilityRole="button" accessibilityLabel={labels.rate}
          accessibilityState={{ expanded: rating }} onPress={() => setRating(value => !value)}
          style={[styles.episodeAction, { backgroundColor: palette.surfaceStrong }]}>
          <Icon spec={actionIcons.star} size={18} color={episode.score == null ? palette.textSecondary : palette.warning} />
        </Pressable> : null}
      </View>
    </View>
  </View>;
}

/** The season page's episode cards, in the web's banner-over-details shape. */
export function DetailEpisodeCards({ title, count, order, orderLabel, onOrderChange, episodes, labels, renderRating, palette, onOpen, onAction, onRate, nativeAnime = false, loadMore, onMore, loadingMore }) {
  const [layout, setLayout] = React.useState('grid');
  const [collapsed, setCollapsed] = React.useState(false);
  return <View style={styles.block}>
    <View style={styles.blockHeader}>
      <Text accessibilityRole="header" style={[styles.blockTitle, { color: palette.text }]}>{title}</Text>
      {nativeAnime ? <View style={styles.railControls}>
        {[['grid', 'fourSquare', 'Card view'], ['list', 'list', 'List view']].map(([value, icon, label]) => <Pressable key={value}
          accessibilityRole="button" accessibilityLabel={label} accessibilityState={{ selected: layout === value }}
          onPress={() => setLayout(value)} style={[styles.roundButton, { backgroundColor: layout === value ? palette.accentStrong : palette.surface }]}>
          <Icon spec={actionIcons[icon]} size={16} color={layout === value ? palette.accentContrast : palette.textMuted} />
        </Pressable>)}
        <Pressable accessibilityRole="button" accessibilityLabel="Toggle section" accessibilityState={{ expanded: !collapsed }}
          onPress={() => setCollapsed(value => !value)} style={styles.railControl}>
          <View style={collapsed ? null : styles.flipped}><Icon spec={actionIcons.chevronDown} size={16} color={palette.textMuted} /></View>
        </Pressable>
      </View> : onOrderChange ? <Pressable accessibilityRole="button" accessibilityLabel={orderLabel}
        accessibilityState={{ selected: order === 'desc' }} onPress={onOrderChange}
        style={[styles.roundButton, { backgroundColor: palette.surfaceStrong }]}>
        <Icon spec={actionIcons.arrowsUpDown} size={18} color={palette.text} />
      </Pressable> : null}
    </View>
    {collapsed ? null : <>
      {episodes.map(episode => <EpisodeCard key={episode.key} episode={episode} palette={palette} labels={labels}
        nativeAnime={nativeAnime} list={layout === 'list'}
        renderRating={renderRating} onOpen={onOpen} onAction={onAction} onRate={onRate} />)}
      {nativeAnime && loadMore ? <Pressable accessibilityRole="button" disabled={loadingMore} onPress={onMore}
        style={[styles.linkButton, { alignSelf: 'center', backgroundColor: palette.surfaceStrong }]}>
        <Text style={[styles.linkText, { color: palette.text }]}>{loadingMore ? 'Loading…' : `Show ${loadMore.label}`}</Text>
      </Pressable> : null}
    </>}
  </View>;
}

function OverlayCard({ src, title, palette, width, height, accessibilityLabel, accessibilityRole, onPress, disabled, highlighted, fillWidth }) {
  const [failed, setFailed] = React.useState(false);
  const uri = failed ? '' : src;
  const frame = [styles.overlayCard, fillWidth ? { flex: 1, aspectRatio: width / height } : { width, height }, {
    backgroundColor: palette.placeholder,
    borderColor: highlighted ? palette.accent : 'transparent',
    borderWidth: highlighted ? 2 : 0,
  }];
  const body = <>
    {uri ? <Image source={{ uri }} resizeMode="cover" style={StyleSheet.absoluteFill} accessible={false}
      onError={() => setFailed(true)} /> : <View style={styles.overlayPlaceholder}>
      <Icon spec={actionIcons.image} size={48} color={palette.textMuted} />
    </View>}
    {[56, 62, 68, 74, 80, 86, 92].map(top => [`${top}%`, 0.14]).map(([top, opacity]) => <View key={top} pointerEvents="none"
      style={[styles.overlayShade, { backgroundColor: palette.background, top, opacity }]} />)}
    <Text numberOfLines={1} style={[styles.overlayTitle, { color: palette.text }]}>{title}</Text>
  </>;
  if (disabled || !onPress) return <View accessible accessibilityLabel={accessibilityLabel} style={frame}>{body}</View>;
  return <Pressable accessibilityRole={accessibilityRole || 'link'} accessibilityLabel={accessibilityLabel} onPress={onPress} style={frame}>{body}</Pressable>;
}

/** The web related-media grid (franchise collection, DLC): three cards a row, current title outlined. */
export function DetailRelatedGrid({ title, items, palette, onOpen, current, moreLabel = 'Show more', lessLabel = 'Show less' }) {
  const [all, setAll] = React.useState(false);
  if (!items.length) return null;
  const shown = all ? items : items.slice(0, 6);
  return <View style={styles.block}>
    <Text accessibilityRole="header" style={[styles.blockTitle, { color: palette.text }]}>{title}</Text>
    <View style={styles.relatedGrid}>
      {shown.map(item => <View key={item.key} style={styles.relatedCell}>
        <OverlayCard src={item.image} title={item.title} palette={palette} width={2} height={3} fillWidth
          accessibilityLabel={item.title} highlighted={Boolean(current && String(item.identity?.mediaId) === String(current))}
          onPress={() => onOpen?.(item)} />
      </View>)}
    </View>
    {items.length > 6 ? <Pressable accessibilityRole="button" onPress={() => setAll(value => !value)} style={styles.showMore}>
      <Text style={[styles.linkText, { color: palette.link }]}>{all ? lessLabel : moreLabel}</Text>
    </Pressable> : null}
  </View>;
}


/** The comic "Issues" cards: cover, title, issue number and date, with Track and Lists. */
export function DetailIssueCards({ title = 'Issues', rows, total, loading, error, layout, onLayout, onOpen, onTrack, onLists, onMore, palette, labels = {} }) {
  const [collapsed, setCollapsed] = React.useState(false);
  const toggle = (value, icon, label) => <Pressable accessibilityRole="button" accessibilityLabel={label}
    accessibilityState={{ selected: layout === value }} onPress={() => onLayout(value)}
    style={[styles.roundButton, { backgroundColor: layout === value ? palette.accentStrong : palette.surfaceStrong }]}>
    <Icon spec={actionIcons[icon]} size={16} color={layout === value ? palette.accentContrast : palette.textMuted} />
  </Pressable>;
  return <View style={styles.block}>
    <View style={styles.blockHeader}>
      <Text accessibilityRole="header" style={[styles.blockTitle, { color: palette.text }]}>{title}</Text>
      <View style={styles.railControls}>
        {toggle('grid', 'fourSquare', 'Card view')}
        {toggle('list', 'list', 'List view')}
        <Pressable accessibilityRole="button" accessibilityLabel="Toggle section" accessibilityState={{ expanded: !collapsed }}
          onPress={() => setCollapsed(value => !value)} style={styles.railControl}>
          <View style={collapsed ? null : styles.flipped}><Icon spec={actionIcons.chevronDown} size={18} color={palette.text} /></View>
        </Pressable>
      </View>
    </View>
    {collapsed ? null : <>
      {rows.map(issue => <View key={issue.key} style={[styles.issueCard, { backgroundColor: palette.surface, borderColor: palette.border }]}>
        <Pressable accessibilityRole="link" accessibilityLabel={issue.title} onPress={() => onOpen(issue)}
          style={layout === 'list' ? styles.issueRow : null}>
          <View style={[layout === 'list' ? styles.issueThumb : styles.issueCover, { backgroundColor: palette.placeholder }]}>
            {issue.image ? <Image source={{ uri: issue.image }} resizeMode="cover" style={StyleSheet.absoluteFill} accessible={false} /> : null}
            {issue.read ? <View style={[styles.issueRead, { backgroundColor: palette.success }]}>
              <Icon spec={actionIcons.check || actionIcons.eye} size={12} color={palette.accentContrast} />
            </View> : null}
          </View>
          <View style={styles.issueText}>
            <Text numberOfLines={1} style={[styles.episodeTitle, { color: palette.text }]}>{issue.title}</Text>
            <Text style={[styles.activity, { color: palette.textMuted }]}>{issue.subtitle}</Text>
          </View>
        </Pressable>
        <View style={styles.issueActions}>
          <Pressable accessibilityRole="button" onPress={() => (onTrack || onOpen)(issue)}
            style={[styles.issueButton, { backgroundColor: palette.accentStrong }]}>
            <Text style={[styles.linkText, { color: palette.accentContrast }]}>{labels.track || 'Track'}</Text>
          </Pressable>
          <Pressable accessibilityRole="button" onPress={() => onLists(issue)}
            style={[styles.issueButton, { borderColor: palette.border, borderWidth: 1 }]}>
            <Text style={[styles.linkText, { color: palette.text }]}>{labels.lists || 'Lists'}</Text>
          </Pressable>
        </View>
      </View>)}
      {loading ? <ActivityIndicator color={palette.accent} /> : null}
      {error ? <Text style={[styles.empty, { color: palette.danger }]}>{error}</Text> : null}
      {rows.length < total ? <Pressable accessibilityRole="button" onPress={onMore} style={styles.showMore}>
        <Text style={[styles.linkText, { color: palette.link }]}>{`Show ${Math.min(20, total - rows.length)} more`}</Text>
      </Pressable> : null}
    </>}
  </View>;
}

const styles = StyleSheet.create({
  poster: { borderRadius: 10, overflow: 'hidden', alignItems: 'center', justifyContent: 'center' },
  posterPlaceholder: { padding: 8, fontSize: 12, lineHeight: 16, textAlign: 'center' },
  hero: { flexDirection: 'row', gap: 16, alignItems: 'center', minWidth: 0 },
  heroBody: { flex: 1, minWidth: 0, gap: 6 },
  seasonSwitch: { flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'flex-start' },
  parent: { fontSize: 13, fontWeight: '600' },
  title: { fontSize: 24, lineHeight: 30, fontWeight: '700', flexShrink: 1 },
  activity: { fontSize: 13, lineHeight: 18 },
  actionBar: { gap: 10 },
  primaryRow: { flexDirection: 'row' },
  primary: { flex: 1, minHeight: 44, flexDirection: 'row', gap: 8, alignItems: 'center', justifyContent: 'center', borderRadius: 8, paddingHorizontal: 12 },
  primaryJoined: { borderTopRightRadius: 0, borderBottomRightRadius: 0 },
  primaryText: { fontSize: 15, fontWeight: '600' },
  edit: { width: 48, alignItems: 'center', justifyContent: 'center', borderTopRightRadius: 8, borderBottomRightRadius: 8, borderLeftWidth: 1 },
  quickRow: { flexDirection: 'row', gap: 8 },
  quick: { flex: 1, minHeight: 44, borderRadius: 8, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  quickGlyph: { fontSize: 18, fontWeight: '600' },
  linkRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  linkButton: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8 },
  linkText: { fontSize: 13, fontWeight: '500' },
  scoreScroll: { gap: 8, alignItems: 'center', paddingRight: 16 },
  scoreRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center' },
  scoreChip: { width: 166, height: 94, flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1, borderRadius: 12, padding: 12 },
  scoreLogo: { width: 36, height: 36, borderRadius: 18, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  scoreLogoImage: { width: 14, height: 14 },
  scorePill: { height: 32, flexDirection: 'row', alignItems: 'center', gap: 6, borderWidth: 1, borderRadius: 16, paddingRight: 12 },
  scorePillLogo: { width: 32, height: 32, marginLeft: -1, borderRadius: 16, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  scorePillText: { fontSize: 14, fontWeight: '600' },
  scoreText: { flex: 1, minWidth: 0, gap: 2 },
  scoreBrand: { fontSize: 9, fontWeight: '800', letterSpacing: 1 },
  scoreValue: { fontSize: 18, lineHeight: 24, fontWeight: '600' },
  graphScrim: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 16 },
  graphCard: { width: '100%', maxWidth: 560, maxHeight: '85%', borderWidth: 1, borderRadius: 16, padding: 16, gap: 12 },
  graphScroll: { maxHeight: 420 },
  graphRow: { flexDirection: 'row', alignItems: 'center', gap: 2, marginBottom: 2 },
  graphCorner: { width: 28, fontSize: 11, textAlign: 'center' },
  graphHead: { width: 40, fontSize: 11, fontWeight: '700', textAlign: 'center' },
  graphCell: { width: 40, height: 26, borderRadius: 4, alignItems: 'center', justifyContent: 'center' },
  graphCellText: { fontSize: 11, fontWeight: '700' },
  graphLegend: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  graphLegendItem: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  graphSwatch: { width: 10, height: 10, borderRadius: 2 },
  heroFrame: { overflow: 'hidden', justifyContent: 'flex-end', marginTop: -44 },
  heroImage: { position: 'absolute', top: 0, left: 0, right: 0 },
  heroFade: { position: 'absolute', left: 0, right: 0, bottom: 0 },
  heroContent: { alignItems: 'center', justifyContent: 'flex-end', gap: 4, paddingHorizontal: 16, paddingBottom: 12 },
  heroLogo: { width: '70%', height: 96, marginBottom: 6 },
  heroTitle: { fontSize: 36, lineHeight: 40, fontWeight: '800', textAlign: 'center' },
  heroSeason: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingVertical: 4 },
  heroSeasonText: { fontSize: 18, lineHeight: 24, fontWeight: '600' },
  heroMeta: { fontSize: 14, lineHeight: 20, textAlign: 'center' },
  backdropBlock: { gap: 10 },
  backdrop: { width: '100%', borderRadius: 12, overflow: 'hidden', justifyContent: 'flex-end', alignItems: 'center' },
  backdropLogo: { width: '60%', height: '45%', marginBottom: 12 },
  trailer: { flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'flex-start' },
  thumb: { width: 128, aspectRatio: 16 / 9, borderRadius: 8, overflow: 'hidden' },
  lightbox: { width: '100%', height: '80%' },

  scoreLabel: { fontSize: 12 },
  card: { borderRadius: 8, padding: 16, gap: 16 },
  cardTitle: { fontSize: 17, fontWeight: '700', textAlign: 'center' },
  lengthCard: { gap: 2, padding: 16 },
  lengthValue: { fontSize: 20, fontWeight: '700' },
  infoGrid: { flexDirection: 'row', flexWrap: 'wrap', rowGap: 12 },
  infoCell: { alignItems: 'center', gap: 2 },
  infoLabel: { fontSize: 14, fontWeight: '600', textAlign: 'center' },
  infoValue: { fontSize: 14, textAlign: 'center' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, justifyContent: 'center' },
  chip: { borderWidth: 1, borderRadius: 14, paddingHorizontal: 12, paddingVertical: 5 },
  chipText: { fontSize: 13 },
  block: { gap: 10 },
  blockHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  blockTitle: { fontSize: 20, fontWeight: '700', flexShrink: 1 },
  roundButton: { width: 36, height: 36, borderRadius: 8, alignItems: 'center', justifyContent: 'center' },
  roundGlyph: { fontSize: 20, fontWeight: '600', lineHeight: 22 },
  empty: { fontSize: 14, lineHeight: 20 },
  loading: { alignItems: 'center', gap: 8, paddingVertical: 16 },
  skeleton: { gap: 16 },
  noteGroup: { gap: 6 },
  noteDate: { fontSize: 12 },
  note: { borderWidth: 1, borderRadius: 10, padding: 16, flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  noteEdit: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' },
  noteText: { flex: 1, minWidth: 0, fontSize: 14, lineHeight: 20 },
  repeatsToggle: { flexDirection: 'row', gap: 8, minHeight: 40, borderRadius: 8, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 12 },
  flipped: { transform: [{ rotate: '180deg' }] },
  historyRow: { borderWidth: 1, borderRadius: 10, padding: 12, flexDirection: 'row', alignItems: 'center', gap: 8 },
  historyBody: { flex: 1, minWidth: 0, gap: 2 },
  episodeCard: { borderRadius: 12, overflow: 'hidden' },
  episodeBanner: { width: '100%', aspectRatio: 16 / 9, justifyContent: 'flex-end' },
  episodeShade: { ...StyleSheet.absoluteFillObject, opacity: 0.2 },
  episodeBannerText: { padding: 16, gap: 2 },
  episodeTitle: { fontSize: 22, lineHeight: 28, fontWeight: '700' },
  episodeSubtitle: { fontSize: 14 },
  episodeEye: { position: 'absolute', top: 12, right: 12, width: 28, height: 28, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  episodeBody: { padding: 16, gap: 12 },
  animeEpisodeRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8 },
  episodePill: { height: 32, borderRadius: 16, paddingHorizontal: 12, alignItems: 'center', justifyContent: 'center' },
  episodeFooter: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', flexWrap: 'wrap', gap: 8 },
  episodeAction: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  rail: { gap: 16 },
  railItem: { gap: 4 },
  railControls: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  railControl: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' },
  overlayCard: { borderRadius: 12, overflow: 'hidden', justifyContent: 'flex-end' },
  overlayPlaceholder: { ...StyleSheet.absoluteFillObject, alignItems: 'center', justifyContent: 'center' },
  overlayShade: { ...StyleSheet.absoluteFillObject },
  overlayTitle: { fontSize: 14, fontWeight: '700', paddingHorizontal: 10, paddingBottom: 8 },
  relatedGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  relatedCell: { width: '31.5%', flexGrow: 0 },
  issueCard: { borderWidth: 1, borderRadius: 12, overflow: 'hidden' },
  issueCover: { width: '100%', aspectRatio: 16 / 9, overflow: 'hidden' },
  issueThumb: { width: 64, height: 64, overflow: 'hidden', borderRadius: 8 },
  issueRow: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 12 },
  issueText: { padding: 12, gap: 4, flexShrink: 1 },
  issueActions: { flexDirection: 'row', gap: 8, paddingHorizontal: 12, paddingBottom: 12 },
  issueButton: { height: 36, borderRadius: 8, paddingHorizontal: 20, alignItems: 'center', justifyContent: 'center' },
  issueRead: { position: 'absolute', top: 8, left: 8, width: 22, height: 22, borderRadius: 11, alignItems: 'center', justifyContent: 'center' },
  showMore: { alignSelf: 'flex-start', paddingVertical: 8 },
  listCard: { gap: 4, alignItems: 'center' },
  railTitle: { fontSize: 13, fontWeight: '600' },
  stepper: { flexDirection: 'row', gap: 8 },
  seasonRow: { gap: 8 },
  seasonChip: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6, gap: 2, alignItems: 'center' },
  step: { flex: 1, minHeight: 40, borderWidth: 1, borderColor: 'transparent', borderRadius: 8, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 8 },
});
