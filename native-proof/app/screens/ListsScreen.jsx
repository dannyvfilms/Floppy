import React, { useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Screen } from '../components/Screen';
import { getActiveAuthSession } from '../data/authSession';
import { createListTransport } from '../data/listTransport';
import { ListsPageView } from '../../../frontend/pages/ListsPageView';
import { Button } from '../../../frontend/ui/Button';
import { ListForm } from '../../../frontend/ui/ListFormView';
import { ListItemPreview, ListItemSearch } from '../../../frontend/ui/ListSearchView';
import { ListRecommendations } from '../../../frontend/ui/ListRecommendationsView';
import { palette, spacing } from '../theme';

export const surface = {
  id: 'LISTS',
  status: 'ported',
  title: 'Lists hub, list forms, add/recommend flows and smart summaries',
  where: 'Lists screen cards, create/edit list form, item search/preview, recommendations approval and deny, saved smart-rule summary',
  note: 'The lists page renders the shared ListsPageView composition (heading, actions, search, tag filter, card grid, empty/loading/error states). Signed-in loads map /api/v1/lists/ and creates, edits and deletes manual lists through the same route. Tags, completion percentages and public slugs are not exposed by the list serializer, so tag chips and completion stay empty; smart lists still have no create/list mapping and add-item, preview and recommendation approval remain local.',
};

const URL_PREFIX = 'https://floppy.example/lists/';
const RESERVED_SLUGS = ['create', 'edit', 'delete'];

const MEDIA_TYPES = [
  { value: 'movie', label: 'Movies' },
  { value: 'tv', label: 'Shows' },
  { value: 'book', label: 'Books' },
  { value: 'game', label: 'Games' },
  { value: 'anime', label: 'Anime' },
];

const PEOPLE = [
  { id: 'avery', name: 'Avery', handle: '@avery' },
  { id: 'morgan', name: 'Morgan', handle: '@morgan' },
  { id: 'sam', name: 'Sam', handle: '@sam' },
  { id: 'riley', name: 'Riley', handle: '@riley' },
  { id: 'jordan', name: 'Jordan', handle: '@jordan' },
];

const CATALOG = [
  {
    id: 'dune-2',
    mediaType: 'movie',
    title: 'Dune: Part Two',
    mediaTypeLabel: 'Movie',
    year: 2024,
    score: 8.6,
    scoreCount: 6124,
    image: 'https://picsum.photos/seed/floppy-add-dune/400/600',
    genres: ['Science Fiction', 'Adventure'],
    synopsis: 'Paul Atreides unites with the Fremen while seeking revenge against the conspirators who destroyed his family.',
    details: { status: 'Released', format: 'Movie', runtime: '2h 46m', studios: ['Legendary Pictures'] },
  },
  {
    id: 'wild-robot',
    mediaType: 'movie',
    title: 'The Wild Robot',
    mediaTypeLabel: 'Movie',
    year: 2024,
    score: 8.2,
    scoreCount: 2841,
    image: 'https://picsum.photos/seed/floppy-add-robot/400/600',
    genres: ['Animation', 'Family'],
    synopsis: 'A shipwrecked robot learns to survive on a wild island and becomes the adoptive parent of an orphaned gosling.',
    details: { status: 'Released', format: 'Movie', runtime: '1h 42m', studios: ['DreamWorks Animation'] },
  },
  {
    id: 'shogun',
    mediaType: 'tv',
    title: 'Shōgun',
    mediaTypeLabel: 'Show',
    year: 2024,
    score: 8.9,
    scoreCount: 5120,
    image: 'https://picsum.photos/seed/floppy-add-shogun/400/600',
    genres: ['Drama', 'History'],
    synopsis: 'In feudal Japan, a shipwrecked English sailor becomes entangled in a struggle for power.',
    details: { status: 'Ended', format: 'TV', seasons: 1, episodes: 10, studios: ['FX Productions'] },
  },
  {
    id: 'severance',
    mediaType: 'tv',
    title: 'Severance',
    mediaTypeLabel: 'Show',
    year: 2022,
    score: 8.8,
    scoreCount: 4380,
    image: 'https://picsum.photos/seed/floppy-add-severance/400/600',
    genres: ['Drama', 'Mystery'],
    synopsis: 'Employees at Lumon Industries have their work memories surgically divided from their personal lives.',
    details: { status: 'Returning Series', format: 'TV', seasons: 2, episodes: 19, studios: ['Red Hour Films'] },
  },
  {
    id: 'ministry-of-time',
    mediaType: 'book',
    title: 'The Ministry of Time',
    mediaTypeLabel: 'Book',
    year: 2024,
    score: 8.1,
    scoreCount: 980,
    image: 'https://picsum.photos/seed/floppy-add-ministry/400/600',
    genres: ['Science Fiction', 'Romance'],
    synopsis: 'A civil servant is assigned to a new colleague rescued from the past, and finds the present shifting around them.',
    details: { format: 'Novel', pages: 352, studios: ['Avid Reader Press'] },
  },
  {
    id: 'piranesi',
    mediaType: 'book',
    title: 'Piranesi',
    mediaTypeLabel: 'Book',
    year: 2020,
    score: 8.7,
    scoreCount: 1540,
    image: 'https://picsum.photos/seed/floppy-add-piranesi/400/600',
    genres: ['Fantasy', 'Mystery'],
    synopsis: 'Piranesi lives in a house with infinite halls, where the tides reveal the only truths he knows.',
    details: { format: 'Novel', pages: 245, studios: ['Bloomsbury'] },
  },
  {
    id: 'balatro',
    mediaType: 'game',
    title: 'Balatro',
    mediaTypeLabel: 'Game',
    year: 2024,
    score: 9.0,
    scoreCount: 3260,
    image: 'https://picsum.photos/seed/floppy-add-balatro/400/400',
    genres: ['Roguelike', 'Card'],
    synopsis: 'A poker-inspired roguelike about building wildly synergistic hands across escalating blinds.',
    details: { format: 'PC', studios: ['LocalThunk'] },
  },
  {
    id: 'hades-2',
    mediaType: 'game',
    title: 'Hades II',
    mediaTypeLabel: 'Game',
    year: 2024,
    score: 9.1,
    scoreCount: 2890,
    image: 'https://picsum.photos/seed/floppy-add-hades/400/400',
    genres: ['Roguelike', 'Action'],
    synopsis: 'Melinoë battles through the underworld to confront the Titan of Time.',
    details: { format: 'PC', studios: ['Supergiant Games'] },
  },
  {
    id: 'frieren',
    mediaType: 'anime',
    title: 'Frieren: Beyond Journey\'s End',
    mediaTypeLabel: 'Anime',
    year: 2023,
    score: 9.0,
    scoreCount: 1760,
    image: 'https://picsum.photos/seed/floppy-add-frieren/400/600',
    genres: ['Adventure', 'Fantasy'],
    synopsis: 'An elf mage retraces a hero\'s journey long after the party has disbanded.',
    details: { status: 'Finished', format: 'TV', seasons: 1, episodes: 28, studios: ['Madhouse'] },
  },
  {
    id: 'blue-eye',
    mediaType: 'anime',
    title: 'Blue Eye Samurai',
    mediaTypeLabel: 'Anime',
    year: 2023,
    score: 8.8,
    scoreCount: 1320,
    image: 'https://picsum.photos/seed/floppy-add-samurai/400/600',
    genres: ['Action', 'Drama'],
    synopsis: 'A mixed-race swordmaster carves a path of revenge through Edo-period Japan.',
    details: { status: 'Returning Series', format: 'TV', seasons: 1, episodes: 8, studios: ['Blue Spirit'] },
  },
];

function cardFor(item) {
  return {
    title: item.title,
    image: { src: item.image, fallback: '', source: 'primary' },
    shape: item.mediaType === 'game' ? 'square' : 'poster',
    statusChip: null,
    cornerChips: [],
    href: null,
    actions: null,
    lines: [{ join: 'plain', parts: [{ text: String(item.year), muted: true }] }],
    rating: item.score == null ? null : { label: String(item.score), value: item.score, scaleMax: 10 },
  };
}

function previewFor(item) {
  return {
    title: item.title,
    mediaTypeLabel: item.mediaTypeLabel,
    year: item.year,
    score: item.score,
    scoreCount: item.scoreCount,
    genres: item.genres,
    synopsis: item.synopsis,
    image: { src: item.image },
    details: item.details,
  };
}

const SEARCH_RESULTS = CATALOG.map(item => ({
  id: item.id,
  mediaType: item.mediaType,
  title: item.title,
  media: cardFor(item),
  preview: previewFor(item),
}));

const SEARCH_IDLE = { query: '', mediaType: 'movie', page: 1 };

function normalizeSlug(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '');
}

function currentUrlFor(list) {
  if (!list || !['public', 'unlisted'].includes(list.visibility)) {
    return '';
  }
  return `${URL_PREFIX}${list.publicSlug || list.id}`;
}

function visibilityLabel(visibility) {
  if (visibility === 'public') return 'Public';
  if (visibility === 'unlisted') return 'Unlisted';
  return 'Private';
}

function memberFromUser(user, role) {
  if (!user) return null;
  return {
    id: String(user.id),
    name: user.username,
    handle: `@${user.username}`,
    role,
  };
}

function listFromApi(list, currentUsername) {
  const owner = list.owner || {};
  const collaborators = list.collaborators || [];
  const viewers = list.viewers || [];
  const isOwner = owner.username === currentUsername;
  const isCollaborator = collaborators.some(member => member.username === currentUsername);
  const members = [
    memberFromUser(owner, 'owner'),
    ...collaborators.map(member => memberFromUser(member, 'collaborator')),
    ...viewers.map(member => memberFromUser(member, 'viewer')),
  ].filter(Boolean);
  const role = isOwner ? 'Owner' : isCollaborator ? 'Collaborator' : 'Viewer';
  return {
    id: String(list.id),
    name: list.name || '',
    description: list.description || '',
    coverUrl: list.image || null,
    isSmart: false,
    source: 'local',
    visibility: list.visibility || (list.is_public ? 'public' : 'private'),
    visibilityLabel: visibilityLabel(list.visibility || (list.is_public ? 'public' : 'private')),
    role,
    isOwner,
    memberCount: members.length,
    members,
    itemsCount: Number(list.items_count) || 0,
    completionPercent: null,
    canEdit: isOwner || isCollaborator,
    canDelete: isOwner,
    allowRecommendations: Boolean(list.allow_recommendations),
    includeNotes: false,
    publicSlug: list.public_slug || '',
    tags: [],
    href: `/lists/${list.id}`,
  };
}

function ListTools({ list, approvals, onEdit, onAdd, onRecommend, onApprovals }) {
  const canAdd = list.canEdit && !list.isSmart;
  if (!list.canEdit && !list.allowRecommendations) {
    return null;
  }
  return <View style={styles.cardActions}>
    {list.canEdit ? <Button label="Edit" tone="surface" onPress={onEdit} /> : null}
    {canAdd ? <Button label="Add item" tone="surface" onPress={onAdd} /> : null}
    {list.allowRecommendations ? <Button label="Recommend" tone="surface" onPress={onRecommend} /> : null}
    {list.canEdit ? <Button label={approvals ? `Approvals (${approvals})` : 'Approvals'}
      tone="surface" onPress={onApprovals} /> : null}
  </View>;
}

export default function ListsScreen({ onBack, navigate }) {
  const [transport] = useState(() => createListTransport());
  const [lists, setLists] = useState([]);
  const [loading, setLoading] = useState(transport.mode === 'server');
  const [loadError, setLoadError] = useState('');
  const [reloadToken, setReloadToken] = useState(0);
  const [search, setSearch] = useState('');
  const [selectedTag, setSelectedTag] = useState('All');
  const [notice, setNotice] = useState(null);
  const [form, setForm] = useState(null);
  const [formErrors, setFormErrors] = useState({});
  const [addFor, setAddFor] = useState(null);
  const [recommendFor, setRecommendFor] = useState(null);
  const [approvalsFor, setApprovalsFor] = useState(null);
  const [searchState, setSearchState] = useState(SEARCH_IDLE);
  const [preview, setPreview] = useState(null);
  const [recommendations, setRecommendations] = useState({});
  const [addedItems, setAddedItems] = useState({});

  useEffect(() => {
    if (transport.mode !== 'server') {
      setLoading(false);
      return undefined;
    }
    let active = true;
    setLoading(true);
    setLoadError('');
    const username = getActiveAuthSession()?.user?.username || '';
    transport.load()
      .then(payload => {
        if (!active) return;
        setLists((payload?.results || []).map(list => listFromApi(list, username)));
        setLoading(false);
      })
      .catch(cause => {
        if (!active) return;
        setLists([]);
        setLoadError(cause?.message || 'Lists could not be loaded from the server.');
        setLoading(false);
      });
    return () => { active = false; };
  }, [transport, reloadToken]);

  const tags = useMemo(() => {
    const values = new Set(['All']);
    lists.forEach(list => (list.tags || []).forEach(tag => values.add(tag)));
    return [...values];
  }, [lists]);

  const filtered = lists.filter(list => {
    const matchesSearch = list.name.toLowerCase().includes(search.toLowerCase());
    const matchesTag = selectedTag === 'All' || list.tags?.includes(selectedTag);
    return matchesSearch && matchesTag;
  });

  const activeList = form
    ? (form.mode === 'edit' ? lists.find(list => list.id === form.listId) : null)
    : null;

  const tagSuggestions = useMemo(() => {
    const values = [];
    lists.forEach(list => (list.tags || []).forEach(tag => values.push(tag)));
    return values;
  }, [lists]);

  const collaboratorSuggestions = useMemo(() => PEOPLE.filter(person => {
    const members = activeList?.members || [];
    return !members.some(member => member.id === person.id);
  }), [activeList]);

  const searchResults = useMemo(() => {
    const query = searchState.query.trim().toLowerCase();
    if (query.length < 2) {
      return [];
    }
    return SEARCH_RESULTS.filter(result =>
      result.mediaType === searchState.mediaType
      && result.title.toLowerCase().includes(query));
  }, [searchState]);

  const searchStatus = useMemo(() => {
    if (!searchState.query.trim()) {
      return 'idle';
    }
    return searchState.query.trim().length < 2 ? 'short' : 'ready';
  }, [searchState]);

  function openForm(mode, listId = null) {
    setForm({ mode, listId });
    setFormErrors({});
  }

  function closeForm() {
    setForm(null);
    setFormErrors({});
  }

  function openAdd(list) {
    if (!list.canEdit || list.isSmart) {
      setNotice('Only manual lists you can edit support adding items.');
      return;
    }
    setSearchState(SEARCH_IDLE);
    setPreview(null);
    setAddFor(list.id);
  }

  function openRecommend(list) {
    if (!list.allowRecommendations) {
      setNotice('Recommendations are not enabled for this list.');
      return;
    }
    setSearchState(SEARCH_IDLE);
    setPreview(null);
    setRecommendFor(list.id);
  }

  function closeSearch() {
    setAddFor(null);
    setRecommendFor(null);
    setPreview(null);
  }

  function updateSearch(patch) {
    setSearchState(current => ({ ...current, ...patch, page: 1 }));
  }

  function selectResult(result) {
    const listId = addFor || recommendFor;
    const mode = addFor ? 'add' : 'recommend';
    const added = addedItems[listId] || [];
    setPreview({
      mode,
      listId,
      result,
      alreadyInList: added.includes(result.id),
      alreadyRecommended: (recommendations[listId] || []).some(rec => rec.catalogId === result.id),
    });
  }

  function confirmPreview() {
    if (!preview) {
      return;
    }
    const { mode, listId, result } = preview;
    if (mode === 'add') {
      setAddedItems(current => ({
        ...current,
        [listId]: [...(current[listId] || []), result.id],
      }));
      setLists(current => current.map(list => list.id === listId
        ? { ...list, itemsCount: list.itemsCount + 1 }
        : list));
      setNotice(`"${result.title}" has been added to the list in this demo.`);
    } else {
      setRecommendations(current => ({
        ...current,
        [listId]: [...(current[listId] || []), {
          id: `demo-${Date.now()}`,
          catalogId: result.id,
          title: result.title,
          recommender: 'Danny',
          dateLabel: 'Just now',
          note: '',
          media: result.media,
        }],
      }));
      setNotice(`Your recommendation for "${result.title}" has been submitted in this demo.`);
    }
    closeSearch();
  }

  function validate(values) {
    const errors = {};
    const name = String(values.name || '').trim();
    if (!name) {
      errors.name = 'Enter a list name.';
    }
    const slug = normalizeSlug(values.publicSlug);
    if (['public', 'unlisted'].includes(values.visibility) && slug) {
      if (/^\d+$/.test(slug)) {
        errors.publicSlug = 'Custom list URLs cannot be only numbers.';
      } else if (RESERVED_SLUGS.includes(slug)) {
        errors.publicSlug = 'That URL is reserved.';
      } else if (lists.some(list => list.id !== form?.listId && normalizeSlug(list.publicSlug) === slug)) {
        errors.publicSlug = 'That URL is already in use.';
      }
    }
    return { errors, name, slug };
  }

  async function submitForm(values) {
    const { errors, name } = validate(values);
    if (Object.keys(errors).length) {
      setFormErrors(errors);
      return;
    }
    const isPublic = values.visibility === 'public';
    const allowRecommendations = isPublic && values.allowRecommendations;
    const numeric = member => /^\d+$/.test(String(member.id));
    const collaborators = (values.members || [])
      .filter(member => numeric(member) && member.role === 'collaborator')
      .map(member => Number(member.id));
    const viewers = (values.members || [])
      .filter(member => numeric(member) && member.role === 'viewer')
      .map(member => Number(member.id));
    if (transport.mode !== 'server') {
      setNotice('Sign in to create or edit lists.');
      return;
    }
    if (values.isSmart) {
      setNotice('Smart-list creation is not exposed by the list API.');
      return;
    }
    try {
      if (form.mode === 'edit') {
        await transport.update({
          listId: form.listId,
          name,
          description: values.description,
          visibility: values.visibility,
          isPublic,
          allowRecommendations,
        });
        setNotice(`"${name}" was saved.`);
      } else {
        await transport.create({
          name,
          description: values.description,
          visibility: values.visibility,
          isPublic,
          allowRecommendations,
          collaborators,
          viewers,
        });
        setNotice(`"${name}" was created.`);
      }
      setReloadToken(current => current + 1);
      closeForm();
    } catch (cause) {
      setFormErrors({ form: cause?.message || 'The list could not be saved.' });
    }
  }

  async function deleteList(list) {
    if (transport.mode !== 'server') {
      setNotice('Sign in to delete lists.');
      return;
    }
    try {
      await transport.remove({ listId: list.id });
      setLists(current => current.filter(entry => entry.id !== list.id));
      setRecommendations(current => {
        const next = { ...current };
        delete next[list.id];
        return next;
      });
      setNotice(`"${list.name}" was deleted.`);
      closeForm();
    } catch (cause) {
      setNotice(cause?.message || 'The list could not be deleted.');
    }
  }

  function approveRecommendation(rec) {
    setRecommendations(current => ({
      ...current,
      [approvalsFor]: (current[approvalsFor] || []).filter(entry => entry.id !== rec.id),
    }));
    setAddedItems(current => ({
      ...current,
      [approvalsFor]: [...(current[approvalsFor] || []), rec.catalogId],
    }));
    setLists(current => current.map(list => list.id === approvalsFor
      ? { ...list, itemsCount: list.itemsCount + 1 }
      : list));
    setNotice(`"${rec.title}" has been added to the list in this demo.`);
  }

  function denyRecommendation(rec) {
    setRecommendations(current => ({
      ...current,
      [approvalsFor]: (current[approvalsFor] || []).filter(entry => entry.id !== rec.id),
    }));
    setNotice(`Recommendation for "${rec.title}" has been removed in this demo.`);
  }

  const formList = form?.mode === 'edit' && activeList
    ? {
        ...activeList,
        urlPrefix: URL_PREFIX,
        currentUrl: currentUrlFor(activeList),
      }
    : {
        name: '',
        description: '',
        visibility: 'private',
        publicSlug: '',
        includeNotes: false,
        allowRecommendations: false,
        isSmart: false,
        tags: [],
        members: [{ id: 'you', name: 'Danny', handle: '@danny', role: 'owner' }],
        urlPrefix: URL_PREFIX,
        currentUrl: '',
      };

  const addList = lists.find(list => list.id === addFor);
  const recommendList = lists.find(list => list.id === recommendFor);
  const approvalsList = lists.find(list => list.id === approvalsFor);

  const listTools = list => <ListTools
    list={list}
    approvals={(recommendations[list.id] || []).length}
    onEdit={() => openForm('edit', list.id)}
    onAdd={() => openAdd(list)}
    onRecommend={() => openRecommend(list)}
    onApprovals={() => setApprovalsFor(list.id)} />;

  return <Screen onBack={onBack}>
    <ListsPageView
      title="Lists"
      subtitle="Curated, smart and shared collections"
      labels={{ search: 'Search lists', searchPlaceholder: 'Search lists...' }}
      palette={palette}
      actions={<>
        <Button label="Public Profile" tone="surface" onPress={() => setNotice('Public profiles use the platform browser or share adapter.')} />
        <Button label="New List" tone="primary" onPress={() => openForm('create')} />
      </>}
      searchValue={search}
      onSearchChange={setSearch}
      tags={tags}
      activeTag={selectedTag}
      onSelectTag={setSelectedTag}
      lists={filtered}
      renderListTools={listTools}
      onOpenList={list => navigate?.('ListDetail', { list })}
      onListAction={(action, list) => {
        if (action.title === 'Settings') {
          openForm('edit', list.id);
        }
      }}
      state={loading ? 'loading' : loadError ? 'error' : filtered.length ? 'ready' : 'empty'}
      error={loadError ? { title: 'Lists could not load', body: loadError } : undefined}
      onRetry={() => setReloadToken(current => current + 1)}
      empty={{
        title: 'No lists found.',
        body: search || selectedTag !== 'All'
          ? 'Clear the search or choose another tag to see your lists.'
          : 'Create a list to collect and order the media you track.',
        actionLabel: 'Create Your First List',
      }}
      onEmptyAction={() => openForm('create')}
      dialogs={<>
        {notice ? <Text style={styles.notice}>{notice}</Text> : null}
        {form ? <ListForm
      key={form.listId || 'create'}
      mode={form.mode}
      list={formList}
      tagSuggestions={tagSuggestions}
      collaboratorSuggestions={collaboratorSuggestions}
      errors={formErrors}
      canDelete={form.mode === 'edit' ? !!activeList?.canDelete : false}
      palette={palette}
      onSubmit={submitForm}
      onDelete={deleteList}
      onClose={closeForm} /> : null}

    {addList && !preview ? <ListItemSearch
      mode="add"
      listName={addList.name}
      query={searchState.query}
      mediaType={searchState.mediaType}
      mediaTypes={MEDIA_TYPES}
      results={searchResults}
      status={searchStatus}
      page={searchState.page}
      totalPages={1}
      palette={palette}
      onQueryChange={value => updateSearch({ query: value })}
      onMediaTypeChange={value => updateSearch({ mediaType: value })}
      onPage={page => setSearchState(current => ({ ...current, page }))}
      onSelectResult={selectResult}
      onClose={closeSearch} /> : null}

    {recommendList && !preview ? <ListItemSearch
      mode="recommend"
      listName={recommendList.name}
      query={searchState.query}
      mediaType={searchState.mediaType}
      mediaTypes={MEDIA_TYPES}
      results={searchResults}
      status={searchStatus}
      page={searchState.page}
      totalPages={1}
      palette={palette}
      onQueryChange={value => updateSearch({ query: value })}
      onMediaTypeChange={value => updateSearch({ mediaType: value })}
      onPage={page => setSearchState(current => ({ ...current, page }))}
      onSelectResult={selectResult}
      onClose={closeSearch} /> : null}

    {preview ? <ListItemPreview
      open
      mode={preview.mode}
      media={preview.result.preview}
      alreadyInList={preview.alreadyInList}
      alreadyRecommended={preview.alreadyRecommended}
      palette={palette}
      onConfirm={confirmPreview}
      onClose={() => setPreview(null)} /> : null}

    {approvalsList ? <ListRecommendations
      listName={approvalsList.name}
      recommendations={recommendations[approvalsList.id] || []}
      canEdit={!!approvalsList.canEdit}
      palette={palette}
      onApprove={approveRecommendation}
      onDeny={denyRecommendation}
      onView={() => {
        setApprovalsFor(null);
        setNotice('Item details use the platform navigation adapter.');
      }}
      onClose={() => setApprovalsFor(null)} /> : null}
      </>}
    />
  </Screen>;
}

const styles = StyleSheet.create({
  cardActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  notice: { color: palette.textMuted, fontSize: 12, lineHeight: 17 },
});
