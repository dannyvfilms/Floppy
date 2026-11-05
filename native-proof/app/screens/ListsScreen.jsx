import React, { useMemo, useState } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';
import { Screen, Section } from '../components/Screen';
import { Note } from '../components/Note';
import { ListCard } from '../../../frontend/ui/ListCard';
import { Button } from '../../../frontend/ui/Button';
import { Badge } from '../../../frontend/ui/Badge';
import { ListForm } from '../../../frontend/ui/ListFormView';
import { ListItemPreview, ListItemSearch } from '../../../frontend/ui/ListSearchView';
import { ListRecommendations } from '../../../frontend/ui/ListRecommendationsView';
import { palette, spacing } from '../theme';

export const surface = {
  id: 'LISTS',
  status: 'ported',
  title: 'Lists hub, list forms and add/recommend flows',
  where: 'Lists screen cards, create/edit list form, item search/preview, recommendations approval and deny',
  note: 'The list hub, create/edit list form, add-item search and preview, recommend flow and recommendations approval/deny use shared React Native presentation with local demo state. Tiers and smart-rule editing remain legacy; server transport and the web list pages remain unchanged.',
};

const tiers = {
  id: 'TIERS',
  title: 'Tier boards',
  where: 'List detail tier view',
  note: 'Tier tiles, ordering and export remain legacy. Tiers and smart-rule editing are not part of this port.',
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

const demoLists = [
  {
    id: '1',
    name: 'Weekend Watchlist',
    description: 'Films and shows for a slow weekend.',
    coverUrl: 'https://picsum.photos/seed/floppy-list-1/400/300',
    isSmart: false,
    source: 'local',
    visibility: 'public',
    visibilityLabel: 'Public',
    role: 'Owner',
    isOwner: true,
    memberCount: 3,
    members: [
      { id: 'you', name: 'Danny', handle: '@danny', role: 'owner' },
      { id: 'sam', name: 'Sam', handle: '@sam', role: 'collaborator' },
      { id: 'riley', name: 'Riley', handle: '@riley', role: 'collaborator' },
    ],
    itemsCount: 12,
    completionPercent: 25,
    canEdit: true,
    canDelete: true,
    allowRecommendations: true,
    includeNotes: true,
    publicSlug: 'weekend-watchlist',
    tags: ['Movies', 'Shows'],
    href: '/demo/lists/1',
  },
  {
    id: '2',
    name: 'Sci-Fi Essentials',
    description: 'The books and films worth revisiting.',
    coverUrl: 'https://picsum.photos/seed/floppy-list-2/400/300',
    isSmart: true,
    source: 'local',
    visibility: 'private',
    visibilityLabel: 'Private',
    role: 'Owner',
    isOwner: true,
    memberCount: 1,
    members: [{ id: 'you', name: 'Danny', handle: '@danny', role: 'owner' }],
    itemsCount: 8,
    completionPercent: 50,
    canEdit: true,
    canDelete: true,
    allowRecommendations: false,
    includeNotes: false,
    publicSlug: '',
    tags: ['Sci-Fi'],
    href: '/demo/lists/2',
  },
  {
    id: '3',
    name: 'Shared with Friends',
    description: 'A public list curated with friends.',
    coverUrl: 'https://picsum.photos/seed/floppy-list-3/400/300',
    isSmart: false,
    source: 'trakt',
    sourceLabel: 'Trakt',
    visibility: 'public',
    visibilityLabel: 'Public',
    role: 'Collaborator',
    isOwner: false,
    memberCount: 5,
    members: [
      { id: 'northstar', name: 'Northstar', handle: '@northstar', role: 'owner' },
      { id: 'you', name: 'Danny', handle: '@danny', role: 'collaborator' },
      { id: 'sam', name: 'Sam', handle: '@sam', role: 'collaborator' },
      { id: 'riley', name: 'Riley', handle: '@riley', role: 'collaborator' },
      { id: 'jordan', name: 'Jordan', handle: '@jordan', role: 'collaborator' },
    ],
    itemsCount: 5,
    completionPercent: 75,
    canEdit: true,
    canDelete: false,
    allowRecommendations: true,
    includeNotes: false,
    publicSlug: 'shared-with-friends',
    tags: ['Movies'],
    href: '/demo/lists/3',
  },
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

const demoRecommendations = {
  1: [
    {
      id: 'rec-1',
      catalogId: 'wild-robot',
      title: 'The Wild Robot',
      recommender: 'Sam',
      dateLabel: '2 days',
      note: 'The whole family loved this one.',
      media: cardFor(CATALOG.find(item => item.id === 'wild-robot')),
    },
    {
      id: 'rec-2',
      catalogId: 'shogun',
      title: 'Shōgun',
      recommender: 'Riley',
      dateLabel: '5 hours',
      note: '',
      media: cardFor(CATALOG.find(item => item.id === 'shogun')),
    },
  ],
  2: [
    {
      id: 'rec-3',
      catalogId: 'ministry-of-time',
      title: 'The Ministry of Time',
      recommender: 'Avery',
      dateLabel: '1 week',
      note: 'A good fit for the time-travel shelf.',
      media: cardFor(CATALOG.find(item => item.id === 'ministry-of-time')),
    },
  ],
  3: [],
};

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
  if (!list || list.visibility !== 'public') {
    return '';
  }
  return `${URL_PREFIX}${list.publicSlug || list.id}`;
}

function visibilityLabel(visibility) {
  return visibility === 'public' ? 'Public' : 'Private';
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
  const [lists, setLists] = useState(demoLists);
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
  const [recommendations, setRecommendations] = useState(demoRecommendations);
  const [addedItems, setAddedItems] = useState({});

  const tags = useMemo(() => {
    const values = ['All', 'Movies', 'Shows', 'Books', 'Games', 'Anime', 'Sci-Fi'];
    return values;
  }, []);

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
    if (values.visibility === 'public' && slug) {
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

  function submitForm(values) {
    const { errors, name, slug } = validate(values);
    if (Object.keys(errors).length) {
      setFormErrors(errors);
      return;
    }
    const isPublic = values.visibility === 'public';
    const allowRecommendations = isPublic && values.allowRecommendations;
    const includeNotes = isPublic && values.includeNotes;

    if (form.mode === 'edit') {
      setLists(current => current.map(list => list.id === form.listId
        ? {
            ...list,
            name,
            description: values.description,
            visibility: values.visibility,
            visibilityLabel: visibilityLabel(values.visibility),
            allowRecommendations,
            includeNotes,
            publicSlug: slug,
            isSmart: values.isSmart,
            tags: values.tags,
            members: values.members,
            memberCount: values.members.length,
          }
        : list));
      setNotice(`"${name}" was saved in this demo. The server save is not connected.`);
    } else {
      const id = `demo-${Date.now()}`;
      const next = {
        id,
        name,
        description: values.description,
        coverUrl: `https://picsum.photos/seed/floppy-list-${id}/400/300`,
        isSmart: values.isSmart,
        source: 'local',
        visibility: values.visibility,
        visibilityLabel: visibilityLabel(values.visibility),
        role: 'Owner',
        isOwner: true,
        memberCount: values.members.length,
        members: values.members,
        itemsCount: 0,
        completionPercent: 0,
        canEdit: true,
        canDelete: true,
        allowRecommendations,
        includeNotes,
        publicSlug: slug,
        tags: values.tags,
        href: `/demo/lists/${id}`,
      };
      setLists(current => [next, ...current]);
      setNotice(`"${name}" was created in this demo. The server save is not connected.`);
    }
    closeForm();
  }

  function deleteList(list) {
    setLists(current => current.filter(entry => entry.id !== list.id));
    setRecommendations(current => {
      const next = { ...current };
      delete next[list.id];
      return next;
    });
    setNotice(`"${list.name}" was deleted in this demo. The server delete is not connected.`);
    closeForm();
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
  const searchList = addList || recommendList;

  return <Screen title="Lists" subtitle="Curated, smart and shared collections" onBack={onBack}>
    <View style={styles.toolbar}>
      <Button label="Public Profile" tone="surface" onPress={() => setNotice('Public profiles use the platform browser or share adapter.')} />
      <Button label="New List" tone="primary" onPress={() => openForm('create')} />
    </View>
    <TextInput
      style={styles.search}
      placeholder="Search lists..."
      value={search}
      onChangeText={setSearch}
      placeholderTextColor={palette.textMuted}
    />
    <View style={styles.tags}>
      {tags.map(tag => (
        <Badge
          key={tag}
          label={tag}
          tone={tag === selectedTag ? 'indigo' : 'outline'}
          palette={{
            indigo: { color: '#fff', backgroundColor: palette.accentStrong },
            outline: { color: palette.textSecondary, borderColor: palette.surfaceMuted, borderWidth: 1 },
          }}
          onPress={() => setSelectedTag(tag)}
        />
      ))}
    </View>
    {notice ? <Text style={styles.notice}>{notice}</Text> : null}
    {filtered.length === 0 ? (
      <View style={styles.state}>
        <Text style={styles.stateText}>No lists found.</Text>
        <Button label="Create Your First List" tone="primary" onPress={() => openForm('create')} />
      </View>
    ) : (
      <Section title="Your lists">
        <View style={styles.grid}>
          {filtered.map(list => (
            <View key={list.id} style={styles.cardBlock}>
              <ListCard
                list={list}
                palette={palette}
                onOpen={() => navigate?.('ListDetail', { list })}
                onAction={(action) => {
                  if (action.title === 'Settings') {
                    openForm('edit', list.id);
                  }
                }}
              />
              <ListTools
                list={list}
                approvals={(recommendations[list.id] || []).length}
                onEdit={() => openForm('edit', list.id)}
                onAdd={() => openAdd(list)}
                onRecommend={() => openRecommend(list)}
                onApprovals={() => setApprovalsFor(list.id)}
              />
            </View>
          ))}
        </View>
      </Section>
    )}
    <Section title="Tiers">
      <Note surface={tiers} />
    </Section>

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
  </Screen>;
}

const styles = StyleSheet.create({
  toolbar: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginBottom: spacing.md },
  search: {
    backgroundColor: palette.surfaceStrong,
    color: palette.text,
    borderRadius: 6,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    marginBottom: spacing.md,
  },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginBottom: spacing.md },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  cardBlock: { gap: spacing.sm },
  cardActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  state: { alignItems: 'center', gap: spacing.sm, padding: spacing.xl },
  stateText: { color: palette.textMuted, fontSize: 14 },
  notice: { color: palette.textMuted, fontSize: 12, lineHeight: 17, marginBottom: spacing.md },
});
