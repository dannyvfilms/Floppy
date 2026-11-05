import React, { useState } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { Badge } from './Badge';
import { Button } from './Button';
import { FormError, FormHeader, FormSelect, FormTextField } from './MediaCardFormControls';

const DEFAULT_PALETTE = {
  background: '#18181b',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentText: '#ffffff',
  danger: '#ef4444',
  focusStyle: {},
};

const DEFAULT_LABELS = {
  createTitle: 'Create New List',
  editTitle: 'Edit List',
  close: 'Close list form',
  name: 'Name',
  nameRequired: 'Enter a list name.',
  description: 'Description',
  visibility: 'Visibility',
  public: 'Public (read-only access)',
  private: 'Private',
  publicHelp: 'Anyone with the link can view this list.',
  privateHelp: 'Only the owner and collaborators can view this list.',
  publicSlug: 'Custom URL',
  publicSlugHelp: 'Lowercase letters, numbers, dashes and underscores. Leave blank to keep the numeric URL.',
  currentUrl: 'Current URL:',
  saveForUrl: 'Save the list to generate its URL.',
  includeNotes: 'Include Notes',
  includeNotesHelp: "Show the owner's notes on public list pages.",
  allowRecommendations: 'Allow recommendations',
  allowRecommendationsHelp: 'Let anyone recommend items for this public list.',
  smart: 'Smart List',
  smartHelp: 'Automatically updates based on media types and filters. Rule editing is not ported here.',
  tags: 'List Tags',
  tagsHelp: 'Separate tags with commas.',
  tagSuggestions: 'Suggested tags',
  collaborators: 'Collaborators',
  collaboratorsHelp: 'People who can view and edit this list.',
  addCollaborator: 'Add collaborator',
  everyoneIsMember: 'Everyone available is already a member.',
  owner: 'Owner',
  collaborator: 'Collaborator',
  remove: 'Remove',
  submitCreate: 'Create List',
  submitEdit: 'Save',
  delete: 'Delete',
  deleteConfirm: 'Delete this list? This cannot be undone.',
  deleteYes: 'Delete list',
  cancel: 'Cancel',
  required: 'Required',
  publicOnly: 'Public lists only',
  activity: 'Activity History',
};

function mergePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function badgePalette(colors) {
  return {
    outline: { color: colors.textSecondary, borderColor: colors.border, borderWidth: 1 },
    indigo: { color: colors.accentText, backgroundColor: colors.accentStrong },
    danger: { color: colors.danger, borderColor: colors.danger, borderWidth: 1 },
    success: { color: '#10b981', borderColor: '#10b981', borderWidth: 1 },
  };
}

function normalizeTag(text) {
  return String(text || '').trim().replace(/\s+/g, ' ');
}

function slugPreview(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '');
}

function uniqueTags(values) {
  const seen = new Set();
  const result = [];
  (values || []).forEach(value => {
    const tag = normalizeTag(value);
    if (!tag) return;
    const key = tag.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    result.push(tag);
  });
  return result;
}

function ToggleRow({ label, help, checked, disabled, onChange, colors, labels }) {
  return <View style={[styles.toggleRow, { backgroundColor: colors.surfaceStrong, opacity: disabled ? 0.6 : 1 }]}>
    <View style={styles.toggleCopy}>
      <Text style={[styles.toggleLabel, { color: colors.textSecondary }]}>{label}</Text>
      {help ? <Text style={[styles.help, { color: colors.textMuted }]}>{help}</Text> : null}
      {disabled ? <Text style={[styles.help, { color: colors.textMuted }]}>{labels.publicOnly}</Text> : null}
    </View>
    <Switch
      accessibilityLabel={label}
      accessibilityState={{ checked, disabled: !!disabled }}
      disabled={!!disabled}
      onValueChange={value => onChange?.(value)}
      value={!!checked}
      trackColor={{ false: colors.surfaceMuted, true: colors.accentStrong }}
      thumbColor={colors.text} />
  </View>;
}

export function ListForm({
  mode = 'create',
  list = {},
  tagSuggestions = [],
  collaboratorSuggestions = [],
  errors = {},
  pending = false,
  canDelete = false,
  labels: suppliedLabels,
  palette,
  onSubmit,
  onDelete,
  onClose,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(suppliedLabels);
  const badges = badgePalette(colors);
  const [name, setName] = useState(list.name || '');
  const [description, setDescription] = useState(list.description || '');
  const [visibility, setVisibility] = useState(list.visibility === 'public' ? 'public' : 'private');
  const [publicSlug, setPublicSlug] = useState(list.publicSlug || '');
  const [includeNotes, setIncludeNotes] = useState(!!list.includeNotes);
  const [allowRecommendations, setAllowRecommendations] = useState(!!list.allowRecommendations);
  const [isSmart, setIsSmart] = useState(!!list.isSmart);
  const [tagText, setTagText] = useState((list.tags || []).join(', '));
  const tags = uniqueTags(tagText.split(','));
  const [members, setMembers] = useState(list.members || []);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const isPublic = visibility === 'public';
  const isEdit = mode === 'edit';
  const urlPrefix = list.urlPrefix || 'https://floppy.example/lists/';
  const listReference = slugPreview(publicSlug) || list.id || '';
  const currentUrl = listReference ? `${urlPrefix}${listReference}` : '';

  function submit() {
    onSubmit?.({
      name,
      description,
      visibility,
      publicSlug,
      includeNotes: isPublic ? includeNotes : false,
      allowRecommendations: isPublic ? allowRecommendations : false,
      isSmart,
      tags,
      members,
    });
  }

  function addTag(tag) {
    setTagText(uniqueTags([...tags, tag]).join(', '));
  }

  function removeMember(id) {
    setMembers(current => current.filter(member => member.id !== id));
  }

  function addMember(name) {
    const id = name.toLowerCase();
    setMembers(current => current.some(member => member.id === id)
      ? current
      : [...current, { id, name, handle: `@${id}`, role: 'collaborator' }]);
  }

  const availableTags = uniqueTags(tagSuggestions).filter(tag => !tags.includes(tag));
  const availablePeople = (collaboratorSuggestions || []).filter(person => !members.some(member => member.id === person.id));
  return <Modal visible transparent animationType="fade" onRequestClose={onClose}>
    <View style={styles.overlay}>
      <Pressable accessible={false} accessibilityLabel={copy.close} onPress={onClose}
        style={[StyleSheet.absoluteFill, { backgroundColor: 'rgba(0, 0, 0, 0.65)' }]} />
      <View accessibilityViewIsModal role="dialog" accessibilityLabel={isEdit ? copy.editTitle : copy.createTitle}
        style={[styles.dialog, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        <View style={styles.headerBlock}>
          <FormHeader title={isEdit ? copy.editTitle : copy.createTitle} closeLabel={copy.close}
            onClose={onClose} palette={colors} />
        </View>
        <ScrollView keyboardShouldPersistTaps="handled" style={styles.scroll}
          contentContainerStyle={styles.body}>
          <FormTextField label={copy.name} required value={name} onChangeText={setName}
            error={errors.name} palette={colors} />
          <FormTextField label={copy.description} value={description} multiline
            onChangeText={setDescription} error={errors.description} palette={colors} />

          <FormSelect label={copy.visibility} value={visibility} palette={colors}
            options={[
              { value: 'public', label: copy.public },
              { value: 'private', label: copy.private },
            ]}
            onChange={value => setVisibility(value)}
            help={isPublic ? copy.publicHelp : copy.privateHelp} />

          {isPublic ? <View style={[styles.panel, { backgroundColor: colors.surfaceStrong }]}>
            <FormTextField label={copy.publicSlug} value={publicSlug} onChangeText={setPublicSlug}
              error={errors.publicSlug} help={copy.publicSlugHelp} palette={colors} />
            <Text style={[styles.help, { color: colors.textMuted }]}>
              {currentUrl ? `${copy.currentUrl} ${currentUrl}` : copy.saveForUrl}
            </Text>
            <Text style={[styles.help, { color: colors.textMuted }]}>{urlPrefix}</Text>
          </View> : null}

          <View style={styles.toggleGroup}>
            <ToggleRow label={copy.includeNotes} help={copy.includeNotesHelp}
              checked={includeNotes} disabled={!isPublic} onChange={setIncludeNotes}
              colors={colors} labels={copy} />
            <ToggleRow label={copy.allowRecommendations} help={copy.allowRecommendationsHelp}
              checked={allowRecommendations} disabled={!isPublic} onChange={setAllowRecommendations}
              colors={colors} labels={copy} />
            <ToggleRow label={copy.smart} help={copy.smartHelp}
              checked={isSmart} onChange={setIsSmart} colors={colors} labels={copy} />
          </View>

          <View style={styles.field}>
            <FormTextField label={copy.tags} value={tagText} onChangeText={setTagText}
              help={copy.tagsHelp} error={errors.tags} palette={colors} />
            {tags.length ? <View style={styles.chipRow}>
              {tags.map(tag => <Badge key={tag} label={tag} tone="outline" palette={badges} />)}
            </View> : null}
            {availableTags.length ? <View style={styles.field}>
              <Text style={[styles.groupLabel, { color: colors.textMuted }]}>{copy.tagSuggestions}</Text>
              <View style={styles.chipRow}>
                {availableTags.map(tag => <Badge key={tag} label={`+ ${tag}`} tone="outline"
                  palette={badges} onPress={() => addTag(tag)} />)}
              </View>
            </View> : null}
          </View>

          <View style={styles.field}>
            <Text style={[styles.groupLabel, { color: colors.textMuted }]}>{copy.collaborators}</Text>
            <Text style={[styles.help, { color: colors.textMuted }]}>{copy.collaboratorsHelp}</Text>
            {members.map(member => <View key={member.id} style={[styles.memberRow, { borderColor: colors.border }]}>
              <View style={styles.memberCopy}>
                <Text style={[styles.memberName, { color: colors.text }]}>{member.name}</Text>
                {member.handle ? <Text style={[styles.help, { color: colors.textMuted }]}>{member.handle}</Text> : null}
              </View>
              <Badge label={member.role === 'owner' ? copy.owner : copy.collaborator}
                tone={member.role === 'owner' ? 'indigo' : 'outline'} palette={badges} />
              {member.role !== 'owner' ? <Button label={copy.remove} tone="ghost-danger"
                onPress={() => removeMember(member.id)} palette={colors} /> : null}
            </View>)}
            {availablePeople.length ? <View style={styles.field}>
              <Text style={[styles.groupLabel, { color: colors.textMuted }]}>{copy.addCollaborator}</Text>
              <View style={styles.chipRow}>
                {availablePeople.map(person => <Badge key={person.id} label={`+ ${person.name}`}
                  tone="outline" palette={badges} onPress={() => addMember(person.name)} />)}
              </View>
            </View> : <Text style={[styles.help, { color: colors.textMuted }]}>{copy.everyoneIsMember}</Text>}
          </View>

          <FormError message={errors.form} palette={colors} />

          {isEdit && confirmDelete ? <View style={[styles.confirm, { borderColor: colors.danger }]}>
            <Text style={[styles.confirmText, { color: colors.danger }]}>{copy.deleteConfirm}</Text>
            <View style={styles.actions}>
              <Button label={copy.deleteYes} tone="danger-solid" onPress={() => onDelete?.(list)} />
              <Button label={copy.cancel} tone="surface" onPress={() => setConfirmDelete(false)} />
            </View>
          </View> : null}

          <View style={styles.actions}>
            <Button label={isEdit ? copy.submitEdit : copy.submitCreate} tone="primary"
              busy={pending} disabled={pending} onPress={submit} palette={colors} />
            <Button label={copy.cancel} tone="surface" onPress={onClose} palette={colors} />
            {isEdit ? <Button label={copy.delete}
              tone={canDelete ? 'danger-solid' : 'surface'} disabled={!canDelete || pending}
              accessibilityLabel={canDelete ? copy.delete : `${copy.delete} (${copy.owner} only)`}
              onPress={() => setConfirmDelete(true)} palette={colors} /> : null}
          </View>
        </ScrollView>
      </View>
    </View>
  </Modal>;
}

const styles = StyleSheet.create({
  overlay: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 16 },
  dialog: { width: '100%', maxWidth: 640, maxHeight: '92%', borderWidth: 1, borderRadius: 12, overflow: 'hidden' },
  headerBlock: { paddingHorizontal: 20, paddingTop: 16, paddingBottom: 8 },
  scroll: { flexGrow: 0 },
  body: { paddingHorizontal: 20, paddingBottom: 20, gap: 14 },
  panel: { borderRadius: 8, padding: 12, gap: 8 },
  toggleGroup: { gap: 8 },
  toggleRow: { flexDirection: 'row', alignItems: 'center', gap: 12, borderRadius: 8, padding: 12 },
  toggleCopy: { flex: 1, minWidth: 0, gap: 2 },
  toggleLabel: { fontSize: 14, fontWeight: '600' },
  field: { gap: 6 },
  groupLabel: { fontSize: 12, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.5 },
  help: { fontSize: 12, lineHeight: 17 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  memberRow: { flexDirection: 'row', alignItems: 'center', gap: 8, borderTopWidth: 1, paddingTop: 8 },
  memberCopy: { flex: 1, minWidth: 0 },
  memberName: { fontSize: 14, fontWeight: '600' },
  confirm: { borderWidth: 1, borderRadius: 8, padding: 12, gap: 10 },
  confirmText: { fontSize: 13, lineHeight: 18, fontWeight: '600' },
  actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
});
