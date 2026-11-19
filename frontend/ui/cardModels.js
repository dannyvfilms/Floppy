import { actionIcons } from './actionIcons';

// Adapters from other kinds of data to the one media card. A card that looks
// like a media card is built here, as a model, instead of as another component:
// the variation lives in these few lines of configuration and nowhere else.
//
// Options a model can set beyond the basics (see MediaCard.jsx):
//   subtitleAbove  put the subtitle lines above the title
//   aspectRatio    any artwork shape, for example 3 / 2 or 460 / 215
//   lines[].expandable   a line that shows two lines and opens on tap
//   cornerChips[].position / .icon / .action   a chip anywhere, as a button if it has an action
//   density: 'compact'   artwork only
//   hoverMetadata  lines wait for the card to be revealed unless a line is `dormant`

const image = (src, fallback = '') => ({ src: src || null, fallback, source: 'primary' });

const line = (text, extra = {}) => (text ? { clamp: true, join: 'plain', parts: [{ text }], ...extra } : null);

// A Statistics highlight: a small label above the title, over wide artwork.
export function highlightCardModel(item = {}, notAvailable = 'N/A') {
  return {
    shape: 'landscape',
    aspectRatio: 3 / 2,
    subtitleAbove: true,
    image: image(item.image),
    title: item.title || notAvailable,
    lines: [line(item.label, { dormant: true })].filter(Boolean),
    statusChip: null,
    cornerChips: [],
    actions: null,
  };
}

// A cast or crew member. The server sends the lines the user's card settings
// enable, each marked dormant (visible at rest) or hover-only.
export function personCardModel(person = {}) {
  const subtitle = person.subtitle || person.role;
  const metaLines = person.cardLines
    ? person.cardLines.map(entry => ({ text: entry.text, dormant: !!(entry.dormant || person.subtitleAlways) }))
    : [
      ...(subtitle ? [{ text: subtitle, dormant: false }] : []),
      ...(person.lines || []).map(text => ({ text, dormant: false })),
    ];
  return {
    shape: 'poster',
    hoverMetadata: true,
    href: person.href,
    recommend: !person.href,
    image: image(person.imageUrl, person.imageFallback),
    title: person.name || 'Unknown Person',
    lines: metaLines.map(entry => line(entry.text, { dormant: entry.dormant, clamp: false })).filter(Boolean),
    statusChip: null,
    cornerChips: person.episodeCount
      ? [{ kind: 'text', position: 'top-right', text: `${person.episodeCount} ${person.episodeCount === 1 ? 'ep' : 'eps'}` }]
      : [],
    actions: null,
  };
}

// A title in a person's credits: the role and the year and type underneath.
export function creditCardModel(entry = {}) {
  const meta = [entry.year, entry.mediaTypeLabel].filter(Boolean).join(' · ');
  const role = entry.role || entry.roleLine;
  const ageLabel = entry.ageLabel || '';
  const chip = entry.watchedRuntimeLabel
    ? { kind: 'text', position: 'top-right', text: entry.watchedRuntimeLabel }
    : entry.voteAverage
      ? { kind: 'text', position: 'top-right', text: `★ ${Number(entry.voteAverage).toFixed(1)}`, color: '#facc15' }
      : null;
  return {
    shape: 'poster',
    href: entry.href,
    image: image(entry.imageUrl, entry.imageFallback),
    title: entry.title,
    accessibilityLabel: [entry.title, role, ageLabel.replace(/\s*\n\s*/g, ', ')].filter(Boolean).join(', '),
    lines: [
      line(role, { clamp: false }),
      ageLabel ? line(ageLabel, { variant: 'credit-age', clamp: false }) : null,
      line(meta, { dormant: true }),
    ].filter(Boolean),
    statusChip: null,
    cornerChips: chip ? [chip] : [],
    actions: null,
  };
}

// A Steam DLC: wide artwork and a title, opening the store page.
export function dlcCardModel(dlc = {}) {
  return {
    shape: 'landscape',
    aspectRatio: 460 / 215,
    href: dlc.url,
    external: true,
    image: image(dlc.image),
    title: dlc.title,
    lines: [],
    statusChip: null,
    cornerChips: [],
    // Not a tracked item, so no tracking or rating: one hover action, like any card's, that opens the store page.
    actions: {
      href: dlc.url,
      external: true,
      items: [{ kind: 'link', tone: 'indigo', title: 'View on Steam', icon: actionIcons.externalLink, href: dlc.url }],
      ordering: null,
      clickable: false,
    },
  };
}

// A related title (a franchise or collection entry); `highlighted` outlines the one being viewed.
export function relatedCardModel(item = {}, highlighted = false) {
  return {
    shape: 'poster',
    highlighted,
    href: item.href,
    image: image(item.image),
    title: item.title,
    lines: [],
    statusChip: null,
    cornerChips: [],
    actions: null,
  };
}

// A row in a ranked list (Statistics): rank, thumbnail, title and one line, either a rating or text.
export function rankedRowModel(item = {}, index = 0, { round = false } = {}) {
  const text = item.value || item.subtitle;
  return {
    layout: 'row',
    rowSize: 'compact',
    rank: item.rank || index + 1,
    artworkShape: round ? 'round' : undefined,
    shape: 'square',
    href: item.href,
    image: image(item.image),
    title: item.title,
    lines: text ? [{ clamp: true, join: 'plain', parts: [{ text, ...(item.value ? { score: true } : {}) }] }] : [],
    statusChip: null,
    cornerChips: [],
    actions: null,
  };
}

// ---- Music and podcasts -------------------------------------------------------------------

const MONTHS = ['Jan.', 'Feb.', 'March', 'April', 'May', 'June', 'July', 'Aug.', 'Sept.', 'Oct.', 'Nov.', 'Dec.'];

function musicDate(value) {
  const [year, month, day] = String(value || '').split('-').map(Number);
  if (!year || !month || !day) return value || 'No date';
  return `${MONTHS[month - 1]} ${day}, ${year}`;
}

const count = (n, one, many) => (n === 1 ? `1 ${one}` : `${n} ${many}`);
const group = (title, items) => ({ title, items, ordering: null, clickable: true });

const trackActions = () => group('Track actions', [
  { kind: 'action', key: 'listen', title: 'Add listen', icon: actionIcons.listAdd, tone: 'indigo' },
  { kind: 'action', key: 'notes', title: 'Track notes', icon: actionIcons.edit, tone: 'surface' },
  { kind: 'action', key: 'history', title: 'View your activity history', icon: actionIcons.history, tone: 'amber' },
]);

const episodeActions = () => group('Episode actions', [
  { kind: 'action', key: 'play', title: 'Add play', icon: actionIcons.listAdd, tone: 'indigo' },
  { kind: 'action', key: 'notes', title: 'Episode notes', icon: actionIcons.edit, tone: 'surface' },
  { kind: 'action', key: 'history', title: 'View your activity history', icon: actionIcons.history, tone: 'amber' },
]);

const scoreRating = score => ({
  label: score == null ? null : String(score),
  value: score,
  scaleMax: 10,
  rateLabel: 'Rate',
});

// An album card. `labels` carries the singular and plural words (track, play, rate).
export function musicAlbumCardModel(album = {}, labels = {}) {
  const trackCount = album.trackCount ?? (album.tracks ? album.tracks.length : null);
  const parts = [];
  if (album.releaseType) parts.push({ text: album.releaseType });
  if (album.year) parts.push({ text: String(album.year), muted: true });
  if (trackCount != null) parts.push({ text: count(trackCount, labels.track, labels.tracks), muted: true });
  return {
    mediaType: 'music',
    shape: 'square',
    href: album.href,
    image: image(album.image),
    title: album.title,
    altTitle: null,
    cornerChips: album.plays ? [{ kind: 'runtime', text: count(album.plays, labels.play, labels.plays) }] : [],
    lines: album.lines && album.lines.length ? album.lines : [{ join: 'dot', parts }],
    rating: album.score == null ? null : { ...scoreRating(album.score), rateLabel: labels.rate },
    ratingEditable: false,
  };
}

// A related artist (band member, "also in"): status, a Former chip and a role line.
export function musicRelationCardModel(relation = {}, labels = {}) {
  return {
    mediaType: 'music',
    shape: 'poster',
    href: relation.href,
    image: image(relation.image),
    title: relation.name,
    altTitle: null,
    statusChip: relation.status ? { status: relation.status, label: relation.status } : null,
    cornerChips: relation.current ? [] : [{ kind: 'label', text: labels.former }],
    lines: relation.role ? [{ join: 'plain', parts: [{ text: relation.role, muted: true }] }] : [],
    rating: relation.score == null ? null : { ...scoreRating(relation.score), rateLabel: labels.rate },
    ratingEditable: false,
  };
}

// A track in an album: number, length, last listen and the collected format. Accepts the page's
// list of listens or the app's play count and last play.
export function musicTrackRowModel(track = {}, { ratingEditable = true } = {}) {
  const listens = track.listens ? track.listens.length : (track.playCount || 0);
  const last = track.listens ? track.listens[0] : track.lastPlayed;
  const collected = track.codec ? [{ text: `Collected: ${track.codec}`, muted: true }] : [];
  return {
    layout: 'row',
    mediaType: 'music',
    title: track.title,
    image: image(track.image || ''),
    altTitle: null,
    statusChip: null,
    lines: [
      {
        join: 'dot',
        parts: [
          { text: `Track ${track.number}${track.disc > 1 ? ` (Disc ${track.disc})` : ''}` },
          ...(track.duration ? [{ text: track.duration, muted: true }] : []),
        ],
      },
      ...(listens || collected.length ? [{
        join: 'dot',
        parts: listens
          ? [
            { text: last ? `Last listened: ${musicDate(last.date)}` : 'Listened', muted: true },
            ...(listens > 1 ? [{ text: `Listened ${listens} times`, muted: true }] : []),
            ...collected,
          ]
          : collected,
      }] : []),
    ],
    rating: scoreRating(track.score),
    ratingEditable,
    actions: trackActions(),
  };
}

// A podcast episode: number, date and length, then its play state.
export function podcastEpisodeRowModel(episode = {}, showImage = '', { ratingEditable = true } = {}) {
  const plays = episode.plays ? episode.plays.length : (episode.played ? 1 : 0);
  const progress = episode.progressLabel || (episode.inProgress && episode.plays?.[0]?.progress) || '';
  const state = episode.inProgress ? 'In progress' : plays ? 'Played' : 'Unplayed';
  return {
    layout: 'row',
    mediaType: 'podcast',
    title: episode.title,
    image: image(showImage),
    altTitle: null,
    statusChip: null,
    lines: [
      {
        join: 'dot',
        parts: [
          { text: `Episode ${episode.number}` },
          ...(episode.published ? [{ text: musicDate(episode.published), muted: true }] : []),
          ...(episode.duration ? [{ text: episode.duration, muted: true }] : []),
        ],
      },
      {
        join: 'dot',
        parts: [
          { text: state, muted: true },
          ...(episode.inProgress && progress ? [{ text: progress, muted: true }] : []),
        ],
      },
    ],
    rating: scoreRating(episode.score),
    ratingEditable,
    actions: episodeActions(),
  };
}

// A custom list: wide cover, a count line, and Settings for editors. Expo builds this from the
// list hub record; the browser gets the same shape from `list_card_model` on the server.
export function listCardModel(list = {}, { hideMetadata = false } = {}) {
  return {
    title: list.name,
    image: { src: list.coverUrl, fallback: '', source: 'primary' },
    shape: 'landscape',
    video: false,
    href: list.href,
    statusChip: null,
    cornerChips: [],
    lines: hideMetadata ? [] : [
      {
        join: 'plain',
        parts: [
          { text: `${list.itemsCount} ${list.itemsCount === 1 ? 'item' : 'items'}` },
          ...(list.completionPercent != null
            ? [{ text: ` · ${list.completionPercent}% completed`, muted: true }]
            : []),
        ],
      },
      ...((list.isSmart || (list.source && list.source !== 'local') || list.visibility || list.role || list.memberCount > 1)
        ? [{
            join: 'plain',
            parts: [
              ...(list.isSmart ? [{ text: 'Smart', muted: true }] : []),
              ...(list.isSmart && (list.source && list.source !== 'local') ? [{ text: ' • ', muted: true }] : []),
              ...(list.source && list.source !== 'local' ? [{ text: list.sourceLabel || list.source, muted: true }] : []),
              ...((list.isSmart || (list.source && list.source !== 'local')) && (list.visibility || list.role || list.memberCount > 1) ? [{ text: ' • ', muted: true }] : []),
              ...(list.visibility ? [{ text: list.visibilityLabel || (list.visibility === 'public' ? 'Public' : list.visibility === 'unlisted' ? 'Unlisted' : list.visibility === 'private' ? 'Private' : list.visibility) }] : []),
              ...(list.visibility && (list.role || list.memberCount > 1) ? [{ text: ' • ', muted: true }] : []),
              ...(list.role ? [{ text: list.role }] : []),
              ...(list.role && list.memberCount > 1 ? [{ text: ' • ', muted: true }] : []),
              ...(list.memberCount > 1 ? [{ text: `${list.memberCount} members`, muted: true }] : []),
            ],
          }]
        : []),
    ],
    rating: list.rating,
    actions: list.canEdit
      ? {
          href: null,
          items: [
            { kind: 'link', tone: 'indigo', title: 'Settings', glyph: '⋯', icon: actionIcons.ellipsis, href: `${list.href}/edit` },
          ],
          ordering: null,
          modals: {},
          csrfToken: '',
          clickable: true,
          title: list.name,
        }
      : null,
  };
}
