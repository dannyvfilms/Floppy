import React, { useEffect, useMemo, useState } from 'react';
import { TagsPageView } from '../../../frontend/pages/TagsPageView';
import { ConfirmDialog } from '../../../frontend/settings/ConfirmDialog';
import { createTagsTransport } from '../data/tagsTransport';
import { sortTags, tagsFromPayload } from '../data/tagsTransportCore';
import { Screen } from '../components/Screen';
import { palette } from '../theme';

export const surface = {
  id: 'TAGS',
  status: 'ported',
  title: 'Tag index with real counts and delete',
  where: 'Tags page; the assignment, bulk-tag and settings filter surfaces stay with TagManagement consumers',
  note: 'The tag index renders the shared TagsPageView composition. Signed-in loads map GET /api/v1/tags/ (with its per-media-type breakdown) and delete maps DELETE /api/v1/tags/{id}/ through tagsTransport, with loading, empty, error/retry and signed-out states. Type chips open that media library. The web page offers delete only, so rename and merge are not offered here either.',
};

const SIGNED_OUT_ERROR = {
  title: 'Sign in to see your tags',
  body: 'Connect your Floppy server to load the tags you created.',
  retryLabel: 'Sign In',
};

export default function TagsScreen({ onBack, navigate }) {
  const [transport] = useState(() => createTagsTransport());
  const [tags, setTags] = useState([]);
  const [loading, setLoading] = useState(transport.mode === 'server');
  const [loadError, setLoadError] = useState('');
  const [reloadToken, setReloadToken] = useState(0);
  const [sort, setSort] = useState('name');
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  const signedOut = transport.mode !== 'server';

  useEffect(() => {
    if (!signedOut) {
      let active = true;
      setLoading(true);
      setLoadError('');
      transport.load()
        .then(payload => {
          if (!active) return;
          setTags(tagsFromPayload(payload));
          setLoading(false);
        })
        .catch(cause => {
          if (!active) return;
          setTags([]);
          setLoadError(cause?.message || 'Tags could not load');
          setLoading(false);
        });
      return () => { active = false; };
    }
    setLoading(false);
    setTags([]);
    setLoadError('');
    return undefined;
  }, [transport, reloadToken, signedOut]);

  const visibleTags = useMemo(() => sortTags(tags, sort), [tags, sort]);

  const state = signedOut
    ? 'error'
    : loading
      ? 'loading'
      : loadError
        ? 'error'
        : 'ready';

  async function confirmDelete() {
    if (!deleteTarget || deleteBusy) return;
    setDeleteBusy(true);
    setDeleteError('');
    try {
      await transport.remove({ tagId: deleteTarget.id });
      setDeleteTarget(null);
      setReloadToken(current => current + 1);
    } catch (cause) {
      setDeleteError(cause?.message || `Could not delete "${deleteTarget.name}".`);
    } finally {
      setDeleteBusy(false);
    }
  }

  return <Screen onBack={onBack}>
    <TagsPageView
      tags={visibleTags}
      sort={sort}
      palette={palette}
      state={state}
      error={signedOut
        ? SIGNED_OUT_ERROR
        : { title: 'Tags could not load', body: loadError }}
      onRetry={signedOut
        ? () => navigate?.('Auth')
        : () => setReloadToken(current => current + 1)}
      onSortChange={setSort}
      onDelete={setDeleteTarget}
      onOpenType={(tag, type) => navigate?.('Library', { mediaType: type.key, tag: tag.name })} />
    <ConfirmDialog
      visible={!!deleteTarget}
      title="Delete tag"
      message={deleteTarget ? `Delete the "${deleteTarget.name}" tag from your library? This removes it from every item.` : ''}
      warning={deleteTarget ? 'This removes the tag from every item that uses it.' : ''}
      confirmLabel="Delete tag"
      cancelLabel="Keep tag"
      busy={deleteBusy}
      error={deleteError}
      palette={palette}
      onCancel={() => { if (!deleteBusy) { setDeleteTarget(null); setDeleteError(''); } }}
      onConfirm={confirmDelete} />
  </Screen>;
}
