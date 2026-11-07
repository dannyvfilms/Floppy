import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Badge } from './Badge';
import { Button } from './Button';
import { MediaCardActionHost } from './MediaCardActionHost';

const FALLBACK_PALETTE = {
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  success: '#10b981',
  danger: '#ef4444',
  backdrop: 'rgba(0, 0, 0, 0.6)',
};

const defaultLabels = {
  title: 'Members & visibility',
  close: 'Close',
  visibility: 'Visibility',
  public: 'Public',
  unlisted: 'Unlisted',
  private: 'Private',
  publicHelp: 'Listed on your profile. Anyone with the link can view this list.',
  unlistedHelp: 'Only people with the link can view it. It is not listed on your profile.',
  privateHelp: 'Only the owner and the people they share it with can view this list.',
  members: 'Members',
  owner: 'Owner',
  collaborator: 'Collaborator',
  viewer: 'Viewer',
  addCollaborator: 'Add collaborator',
  everyoneIsMember: 'Everyone available is already a member.',
  remove: 'Remove',
  links: 'Links & export',
  rss: 'RSS feed',
  radarr: 'Radarr',
  sonarr: 'Sonarr',
  exportCsv: 'Export CSV',
  smart: 'Smart',
};

const VISIBILITY_OPTIONS = [
  { value: 'public', label: 'public' },
  { value: 'unlisted', label: 'unlisted' },
  { value: 'private', label: 'private' },
];

function mergePalette(palette) {
  return { ...FALLBACK_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...defaultLabels, ...(labels || {}) };
}

function badgePalette(colors) {
  return {
    outline: { color: colors.textSecondary, borderColor: colors.border, borderWidth: 1 },
    indigo: { color: '#ffffff', backgroundColor: colors.accentStrong },
    success: { color: colors.success },
    danger: { color: colors.danger },
  };
}

function visibilityLabel(visibility, copy) {
  return visibility === 'public' ? copy.public
    : visibility === 'unlisted' ? copy.unlisted
      : visibility === 'private' ? copy.private
        : visibility;
}

export function ListMembershipSection({
  list,
  palette,
  labels,
  suggestions = [],
  onChangeVisibility,
  onAddMember,
  onRemoveMember,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const badges = badgePalette(colors);
  const members = list.members || [];
  const canEdit = !!list.canEdit;
  const isOwner = !!list.isOwner;
  return <View style={styles.section}>
    <View style={styles.sectionHeader}>
      <Text style={[styles.heading, { color: colors.textSecondary }]}>{copy.visibility}</Text>
      {list.isSmart ? <Badge label={copy.smart} tone="indigo" palette={badges} /> : null}
      {list.source && list.source !== 'local'
        ? <Badge label={list.sourceLabel || list.source} tone="outline" palette={badges} />
        : null}
    </View>
    {canEdit ? <View style={styles.segment}>
      {VISIBILITY_OPTIONS.map(option => <Button
        key={option.value}
        label={copy[option.label]}
        tone={list.visibility === option.value ? 'primary' : 'surface'}
        onPress={() => onChangeVisibility?.(option.value)} />)}
    </View> : <View style={styles.badgeRow}>
      <Badge label={visibilityLabel(list.visibility, copy)} tone="outline" palette={badges} />
    </View>}
    <Text style={[styles.help, { color: colors.textMuted }]}>
      {list.visibility === 'public'
        ? copy.publicHelp
        : list.visibility === 'unlisted' ? copy.unlistedHelp : copy.privateHelp}
    </Text>

    <Text style={[styles.heading, { color: colors.textSecondary, marginTop: 4 }]}>{copy.members}</Text>
    {members.map(member => <View key={member.id} style={[styles.member, { borderColor: colors.border }]}>
      <View style={styles.memberCopy}>
        <Text style={[styles.memberName, { color: colors.text }]}>{member.name}</Text>
        {member.handle ? <Text style={[styles.memberHandle, { color: colors.textMuted }]}>
          {member.handle}
        </Text> : null}
      </View>
      <Badge
        label={member.role === 'owner'
          ? copy.owner
          : member.role === 'viewer' ? copy.viewer : copy.collaborator}
        tone={member.role === 'owner' ? 'indigo' : 'outline'}
        palette={badges} />
      {canEdit && isOwner && member.role !== 'owner' ? <Button
        label={copy.remove}
        tone="ghost-danger"
        onPress={() => onRemoveMember?.(member.id)} /> : null}
    </View>)}

    {canEdit && isOwner ? <View style={styles.addBlock}>
      <Text style={[styles.help, { color: colors.textMuted }]}>{copy.addCollaborator}</Text>
      {suggestions.length === 0 ? <Text style={[styles.help, { color: colors.textMuted }]}>
        {copy.everyoneIsMember}
      </Text> : <View style={styles.badgeRow}>
        {suggestions.map(name => <Badge
          key={name}
          label={`+ ${name}`}
          tone="outline"
          palette={badges}
          onPress={() => onAddMember?.(name)} />)}
      </View>}
    </View> : null}
  </View>;
}

export function ListShareLinks({
  links,
  palette,
  labels,
  onOpenLink,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const rows = [
    { key: 'rss', label: copy.rss },
    { key: 'radarr', label: copy.radarr },
    { key: 'sonarr', label: copy.sonarr },
    { key: 'exportCsv', label: copy.exportCsv },
  ].filter(row => links && links[row.key]);
  if (rows.length === 0) {
    return null;
  }
  return <View style={[styles.links, { borderColor: colors.border }]}>
    <Text style={[styles.heading, { color: colors.textSecondary }]}>{copy.links}</Text>
    {rows.map(row => <Pressable
      key={row.key}
      accessibilityRole="link"
      accessibilityLabel={row.label}
      onPress={() => onOpenLink?.(row)}
      style={[styles.linkRow, { borderColor: colors.border }]}>
      <Text style={[styles.linkLabel, { color: colors.text }]}>{row.label}</Text>
      <Text style={[styles.linkGlyph, { color: colors.textMuted }]}>↗</Text>
    </Pressable>)}
  </View>;
}

export function ListMembershipPopup({
  open = false,
  list,
  palette,
  labels,
  suggestions = [],
  onClose,
  onChangeVisibility,
  onAddMember,
  onRemoveMember,
  onOpenLink,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  return <MediaCardActionHost
    open={open}
    action={{ title: copy.title }}
    labels={{ close: copy.close }}
    palette={{ ...colors, backdrop: colors.backdrop }}
    onClose={onClose}>
    <ListMembershipSection
      list={list}
      palette={colors}
      labels={copy}
      suggestions={suggestions}
      onChangeVisibility={onChangeVisibility}
      onAddMember={onAddMember}
      onRemoveMember={onRemoveMember} />
    <ListShareLinks
      links={list.links}
      palette={colors}
      labels={copy}
      onOpenLink={onOpenLink} />
  </MediaCardActionHost>;
}

const styles = StyleSheet.create({
  section: { gap: 8 },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  heading: { fontSize: 12, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.5 },
  segment: { flexDirection: 'row', gap: 8 },
  badgeRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  help: { fontSize: 12, lineHeight: 17 },
  member: { flexDirection: 'row', alignItems: 'center', gap: 8, borderTopWidth: 1, paddingTop: 8 },
  memberCopy: { flex: 1, minWidth: 0 },
  memberName: { fontSize: 14, fontWeight: '600' },
  memberHandle: { fontSize: 12 },
  addBlock: { gap: 6, marginTop: 4 },
  links: { borderTopWidth: 1, marginTop: 4, paddingTop: 10, gap: 6 },
  linkRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderTopWidth: 1, paddingVertical: 8 },
  linkLabel: { fontSize: 14, fontWeight: '500' },
  linkGlyph: { fontSize: 14 },
});
