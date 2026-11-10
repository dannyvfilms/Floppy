import React, { useEffect, useMemo, useState } from 'react';
import { Text } from 'react-native';
import { SearchPageView } from '../../../frontend/pages/SearchPageView';
import { ManualEntryView } from '../../../frontend/pages/ManualEntryView';
import { Button } from '../../../frontend/ui/Button';
import { Screen } from '../components/Screen';
import { palette } from '../theme';
import { createSearchTransport } from '../data/searchTransport';
import SearchResultsSlot from '../surfaces/SearchResultsSlot';

// The web page has no search field of its own: the header search (ShellSlot)
// submits here with `query` and `mediaType`, so the page only renders results.
// It opens empty until a query arrives in the route params.
const pageTop = { paddingTop: 24 };

function CreateEntry() {
  const transport = useMemo(() => createSearchTransport(), []);
  const [options, setOptions] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState({ media_type: 'tv', season_number: '1', episode_number: '1', status: 'Planning' });
  const [parent, setParent] = useState({ query: '', selectedId: null, results: [], state: 'idle' });
  const [parentAttempt, setParentAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setError('');
    transport.loadManualOptions().then(value => {
      if (!active) return;
      setOptions(value);
      setDraft(current => ({ ...current, status: value.default_status }));
    }).catch(cause => { if (active) setError(cause?.message || 'Could not load the form.'); });
    return () => { active = false; };
  }, [transport, attempt]);
  useEffect(() => {
    if (!['season', 'episode'].includes(draft.media_type) || parent.selectedId || parent.query.trim().length < 2) return undefined;
    let active = true;
    const timer = setTimeout(() => {
      setParent(current => ({ ...current, state: 'loading' }));
      transport.loadParents({ kind: draft.media_type === 'season' ? 'tv' : 'season', query: parent.query }).then(value => {
        if (active) setParent(current => ({ ...current, state: 'ready', results: value.results || [] }));
      }).catch(() => { if (active) setParent(current => ({ ...current, state: 'error', results: [] })); });
    }, 300);
    return () => { active = false; clearTimeout(timer); };
  }, [transport, draft.media_type, parent.query, parent.selectedId, parentAttempt]);
  function change(name, value) {
    setDraft(current => ({ ...current, [name]: value }));
    if (name === 'media_type') setParent({ query: '', selectedId: null, results: [], state: 'idle' });
    setError('');
    setMessage('');
  }
  async function submit() {
    if (['season', 'episode'].includes(draft.media_type) && !parent.selectedId) {
      setError(draft.media_type === 'season' ? 'Please select a parent TV show from the dropdown' : 'Please select a parent Season from the dropdown');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const result = await transport.createManualEntry({ ...draft,
        ...(draft.media_type === 'season' ? { parent_tv: parent.selectedId } : {}),
        ...(draft.media_type === 'episode' ? { parent_season: parent.selectedId } : {}) });
      setMessage(`${result.title} added successfully.`);
      setDraft({ media_type: 'tv', season_number: '1', episode_number: '1', status: options.default_status });
      setParent({ query: '', selectedId: null, results: [], state: 'idle' });
    } catch (cause) {
      const formErrors = Object.entries(cause?.errors || {})
        .flatMap(([field, messages]) => (Array.isArray(messages) ? messages : [messages]).map(message => `${field}: ${message}`));
      setError(formErrors.join('\n') || cause?.message || 'The entry could not be created.');
    } finally {
      setSaving(false);
    }
  }
  if (!options) return <>
    <Text style={{ color: palette.textMuted }}>{error || 'Loading...'}</Text>
    {error ? <Button label="Try again" onPress={() => setAttempt(value => value + 1)} /> : null}
  </>;
  return <ManualEntryView palette={palette} options={options} draft={draft} onChange={change}
    parent={parent} onParentQuery={query => setParent({ query, selectedId: null, results: [], state: 'idle' })}
    onSelectParent={row => setParent({ query: row.title, selectedId: row.id, results: [], state: 'idle' })}
    onRetryParent={() => setParentAttempt(value => value + 1)} onSubmit={submit}
    saving={saving} message={message} error={error} />;
}

export default function SearchScreen({ params, navigate }) {
  return <Screen chrome={false} contentStyle={pageTop}>
    {params?.createEntry ? <CreateEntry /> : <SearchPageView
      results={<SearchResultsSlot
        query={params?.query || ''}
        mediaType={params?.mediaType || 'all'}
        navigate={navigate}
        onOpenDetail={card => navigate('Detail', { item: card })}
      />}
    />}
  </Screen>;
}
