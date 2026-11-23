import React, { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from './Button';
import { CollectionGroup, CollectionRow, CollectionSelectRow, CollectionSwitchRow, CollectionTextRow } from './CollectionCopies';
import { FormError } from './MediaCardFormControls';

// The Tracking tabs in the iOS grouped-list layout the Collection modal and the Media Details
// sidebar use. Native only: web keeps the compact form bodies in TrackFormTabs (see the
// component register entry for TRACK-FORM).

function Empty({ text, palette }) {
  return <Text style={[styles.empty, { color: palette.textMuted }]}>{text}</Text>;
}

// A row with a second muted line beneath it, for entries that carry a detail.
function DetailRow({ label, value, detail, palette }) {
  return <View>
    <CollectionRow label={label} value={value} palette={palette} />
    {detail ? <Text style={[styles.detail, { color: palette.textMuted }]}>{detail}</Text> : null}
  </View>;
}

function TagsBody({ tab, palette, labels, onTagToggle, onTagCreate }) {
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const tags = tab.tags || [];
  return <View style={styles.stack}>
    {tags.length ? <CollectionGroup title={labels.tags} palette={palette}>
      {tags.map(tag => <View key={tag.id}>
        <CollectionSwitchRow label={tag.name} value={tag.hasTag} disabled={tag.pending}
          onValueChange={() => onTagToggle?.(tag)} palette={palette} />
        {tag.error ? <Text accessibilityRole="alert" style={[styles.detail, { color: palette.danger }]}>{tag.error}</Text> : null}
      </View>)}
    </CollectionGroup> : <Empty text={labels.noTags} palette={palette} />}
    <CollectionGroup palette={palette}>
      <CollectionTextRow label={labels.newTag} value={draft} placeholder={labels.newTag} palette={palette}
        onChangeText={value => { setDraft(value); setError(''); }} />
    </CollectionGroup>
    <View style={styles.actions}>
      <Button label={labels.addTag} busy={busy} disabled={busy || !draft.trim()} palette={palette} onPress={async () => {
        setBusy(true);
        setError('');
        try {
          await onTagCreate?.(draft.trim());
          setDraft('');
        } catch (failure) {
          setError(failure.message || labels.tagFailed);
        }
        setBusy(false);
      }} />
    </View>
    {error ? <FormError message={error} palette={palette} /> : null}
  </View>;
}

function MetadataBody({ tab, palette, labels, onArtworkSave }) {
  const [imageUrl, setImageUrl] = useState(tab.imageUrl || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { setImageUrl(tab.imageUrl || ''); }, [tab.imageUrl]);
  return <View style={styles.stack}>
    {(tab.fields || []).length ? <CollectionGroup title={labels.metadata} palette={palette}>
      {tab.fields.map(field => <CollectionRow key={field.label} label={field.label} value={field.value}
        multiline palette={palette} />)}
    </CollectionGroup> : null}
    <CollectionGroup palette={palette}>
      <CollectionTextRow label={labels.artwork} value={imageUrl} editable={Boolean(tab.canEditArtwork)}
        placeholder="https://" palette={palette} onChangeText={value => { setImageUrl(value); setError(''); }} />
    </CollectionGroup>
    {!tab.canEditArtwork ? <Text style={[styles.detail, { color: palette.textMuted }]}>{labels.artworkUnavailable}</Text> : null}
    <View style={styles.actions}>
      <Button label={labels.saveArtwork} busy={busy} disabled={busy || !tab.canEditArtwork} palette={palette}
        onPress={async () => {
          setBusy(true);
          setError('');
          try {
            await onArtworkSave?.(imageUrl.trim());
          } catch (failure) {
            setError(failure.message || labels.artworkFailed);
          }
          setBusy(false);
        }} />
    </View>
    {error ? <FormError message={error} palette={palette} /> : null}
  </View>;
}

function EntriesBody({ tab, palette, title, emptyText }) {
  const entries = tab.entries || [];
  if (!entries.length) return <Empty text={emptyText} palette={palette} />;
  return <CollectionGroup title={title} palette={palette}>
    {entries.map(entry => <DetailRow key={entry.id} label={entry.title} value={entry.date}
      detail={entry.detail} palette={palette} />)}
  </CollectionGroup>;
}

function StatusHistoryBody({ tab, palette, labels }) {
  const changes = tab.changes || [];
  if (!changes.length) return <Empty text={labels.noStatusChanges} palette={palette} />;
  return <CollectionGroup title={labels.statusHistory} palette={palette}>
    {changes.map(change => <DetailRow key={change.id}
      label={`${change.old ? `${change.old} → ` : ''}${change.next || labels.noStatus}`}
      value={change.date} palette={palette}
      detail={change.reason ? `by ${change.reason}` : labels.sourceNotRecorded} />)}
  </CollectionGroup>;
}

function DiscoverBody({ tab, palette, labels, onDiscoverToggle, renderSelectPicker }) {
  const initial = tab.hidden ? 'hidden' : 'visible';
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { setValue(initial); }, [initial]);
  const changed = value !== initial;
  return <View style={styles.stack}>
    <CollectionGroup title={labels.discoverTitle || labels.discover} palette={palette}>
      <CollectionSelectRow label={labels.discoverStatus || 'Status'} value={value} palette={palette}
        renderPicker={renderSelectPicker} filter popover
        options={[{ value: 'visible', label: labels.discoverVisible || 'Visible' },
          { value: 'hidden', label: labels.discoverHiddenOption || 'Hidden' }]}
        onChange={event => setValue(event.target.value)} />
    </CollectionGroup>
    {labels.discoverHelp ? <Text style={[styles.detail, { color: palette.textMuted }]}>{labels.discoverHelp}</Text> : null}
    <View style={styles.actions}>
      <Button label={labels.save || 'Save'} tone={changed ? 'primary' : 'surface'} busy={busy} palette={palette}
        disabled={busy || !tab.canToggle || !changed} onPress={async () => {
          setBusy(true);
          setError('');
          try {
            await onDiscoverToggle?.(value === 'hidden', tab.itemId);
          } catch (failure) {
            setError(failure.message || labels.discoverFailed);
          }
          setBusy(false);
        }} />
    </View>
    {error ? <FormError message={error} palette={palette} /> : null}
  </View>;
}

// Returns the grouped body for a loaded tab, or null for a kind it does not know.
export function GroupedTabBody({ tab, palette, labels, handlers }) {
  if (tab.kind === 'tags') return <TagsBody tab={tab} palette={palette} labels={labels}
    onTagToggle={handlers.onTagToggle} onTagCreate={handlers.onTagCreate} />;
  if (tab.kind === 'metadata') return <MetadataBody tab={tab} palette={palette} labels={labels}
    onArtworkSave={handlers.onArtworkSave} />;
  if (tab.kind === 'collection') return <EntriesBody tab={tab} palette={palette} title={labels.collection}
    emptyText={labels.noCollection} />;
  if (tab.kind === 'plays') return <EntriesBody tab={tab} palette={palette} title={tab.label || labels.plays}
    emptyText={labels.noPlays} />;
  if (tab.kind === 'status-history') return <StatusHistoryBody tab={tab} palette={palette} labels={labels} />;
  if (tab.kind === 'discover') return <DiscoverBody tab={tab} palette={palette} labels={labels}
    onDiscoverToggle={handlers.onDiscoverToggle} renderSelectPicker={handlers.renderSelectPicker} />;
  return null;
}

const styles = StyleSheet.create({
  stack: { gap: 16 },
  empty: { fontSize: 15, lineHeight: 21, paddingVertical: 8 },
  detail: { fontSize: 13, lineHeight: 18, paddingHorizontal: 16, paddingBottom: 10, marginTop: -4 },
  actions: { flexDirection: 'row', justifyContent: 'flex-end' },
});
