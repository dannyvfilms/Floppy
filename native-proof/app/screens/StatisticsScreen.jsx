import React, { useEffect, useMemo, useState } from 'react';
import { StatisticsView } from '../../../frontend/pages/StatisticsView';
import { Screen } from '../components/Screen';
import { palette, statisticsPalette } from '../theme';
import {
  StatisticsBanner,
  StatisticsPreferencesButton,
  StatisticsPreferencesModal,
} from '../../../frontend/ui/StatisticsPreferences';
import {
  createStatisticsTransport,
  featuredFromPerson,
  statisticsModelFromPayload,
  talentFromPayload,
} from '../data/statisticsTransport';

export const surface = {
  id: 'STATISTICS',
  status: 'in_progress',
  title: 'Statistics summary, charts, talent and per-media overviews',
  where: 'Statistics screen summary cards, highlights, range/compare/media-type controls, charts, talent and per-media-type overviews',
  note: 'The shared StatisticsView owns the heading, summary/comparison/charts/talent/overviews order and section states. Everything comes from /api/v1/statistics: overview (range, Compare-to section with deltas, server media-type gate), talent (role leaders, studios, taste signals, featured repeat player), preferences (compare mode, default range, media types, sorts) and featured-person selection. The range picker highlights the server-resolved range, named ranges resolve on the server, and custom ranges send explicit dates. The Statistics preferences modal (activity view, duration format, week start, rating scale, anime split) saves through PATCH /api/v1/statistics/preferences/ and the screen shows the Building and Refreshing banners. iOS and Android runtime are unverified.',
};

const labels = {
  empty: 'No content logged',
  emptyCopy: 'No media items were logged during the selected time period.',
};

const signedOutLabels = {
  empty: 'Sign in to see your statistics',
  emptyCopy: 'Statistics are calculated on the server from your tracked history.',
};

const talentLabels = {
  loading: 'Loading statistics…',
};

function formatDay(value) {
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function rangeOptionsFrom(names) {
  return [
    ...names.map(value => ({ value, label: value })),
    { value: 'custom', label: 'Custom range', custom: true },
  ];
}

export default function StatisticsScreen({ navigate, onBack }) {
  const transport = useMemo(() => createStatisticsTransport(), []);
  const server = transport.mode === 'server';
  // Empty means "the account's own default range"; the server answers with it.
  const [rangeRequest, setRangeRequest] = useState({});
  const [compare, setCompare] = useState(undefined);
  const [rangeNames, setRangeNames] = useState([]);
  const [selectedTypes, setSelectedTypes] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [modelState, setModelState] = useState(server ? 'loading' : 'empty');
  const [reloadKey, setReloadKey] = useState(0);
  const [talentKey, setTalentKey] = useState(0);
  const [payload, setPayload] = useState(null);
  const [talentPayload, setTalentPayload] = useState(null);
  const [talentState, setTalentState] = useState(server ? 'loading' : 'ready');
  const [featuredOverride, setFeaturedOverride] = useState(null);
  const [prefs, setPrefs] = useState(null);
  const [prefsOpen, setPrefsOpen] = useState(false);
  const [prefsSaving, setPrefsSaving] = useState(false);
  const [prefsError, setPrefsError] = useState('');
  const [bannerHidden, setBannerHidden] = useState(false);

  const rangeKey = JSON.stringify(rangeRequest);

  useEffect(() => {
    if (!server) return undefined;
    let cancelled = false;
    transport.loadPreferences().then(prefs => {
      if (cancelled) return;
      setRangeNames(prefs?.choices?.default_range || []);
      setPrefs(prefs);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [transport, server]);

  useEffect(() => {
    if (!server) {
      setPayload(null);
      setModelState('empty');
      setRefreshing(false);
      return undefined;
    }
    let cancelled = false;
    setModelState(current => (current === 'ready' || current === 'refreshing' ? 'refreshing' : 'loading'));
    transport.loadModel({ ...rangeRequest, compare }).then(data => {
      if (cancelled) return;
      setPayload(data || null);
      setModelState('ready');
      setRefreshing(false);
    }).catch(error => {
      if (cancelled) return;
      console.warn('Statistics could not load', error);
      setModelState('error');
      setRefreshing(false);
    });
    return () => { cancelled = true; };
  }, [transport, server, reloadKey, rangeKey, compare]);

  // The talent section is its own request, like the web fragment, so the
  // summary never waits on the featured-player scan.
  useEffect(() => {
    if (!server) return undefined;
    let cancelled = false;
    setTalentState('loading');
    setFeaturedOverride(null);
    transport.loadTalent({ ...rangeRequest, compare }).then(data => {
      if (cancelled) return;
      setTalentPayload(data || null);
      setTalentState('ready');
    }).catch(error => {
      if (cancelled) return;
      console.warn('Statistics talent could not load', error);
      setTalentState('error');
    });
    return () => { cancelled = true; };
  }, [transport, server, reloadKey, talentKey, rangeKey, compare]);

  const remote = useMemo(
    () => (payload ? statisticsModelFromPayload(payload, selectedTypes || payload.media_types?.selected || []) : null),
    [payload, selectedTypes],
  );
  const types = selectedTypes || remote?.selectedMediaTypes || [];

  const loading = modelState === 'loading';
  const error = modelState === 'error';
  const empty = !server || (modelState === 'ready' && Boolean(remote)
    && !Number(remote.summary.total || 0)
    && !(remote.highlights || []).length
    && !(remote.overviews || []).length);

  const range = useMemo(() => {
    const info = remote?.range;
    const name = info?.name || '';
    const options = rangeOptionsFrom(rangeNames.length ? rangeNames : (name ? [name] : []));
    if (!info) return { selected: '', options };
    const custom = !name;
    const all = name === 'All Time';
    const dateLabel = all
      ? 'Every tracked day'
      : info.startDate && info.endDate
        ? (info.startDate === info.endDate ? formatDay(info.startDate) : `${formatDay(info.startDate)} - ${formatDay(info.endDate)}`)
        : '';
    return {
      selected: custom ? 'custom' : name,
      value: custom ? 'custom' : name,
      label: custom ? dateLabel : name,
      dateLabel,
      startDate: info.startDate,
      endDate: info.endDate,
      options: options.map(option => (option.value === name ? { ...option, dateLabel } : option)),
    };
  }, [remote, rangeNames]);

  const model = useMemo(() => ({
    range,
    mediaTypes: { selected: types, options: remote?.mediaTypeOptions || [] },
    summary: remote?.summary || {},
    highlights: remote?.highlights || [],
    scaleMax: remote?.scaleMax || 10,
    loading,
    error,
    empty,
    refreshing: refreshing || modelState === 'refreshing' || Boolean(remote?.building),
    updatedLabel: '',
  }), [range, types, remote, loading, error, empty, refreshing, modelState]);

  const featured = useMemo(
    () => featuredOverride || featuredFromPerson(talentPayload?.featuredPerson),
    [featuredOverride, talentPayload],
  );

  const chartModel = useMemo(() => ({
    ...(remote?.charts || {}),
    featured,
    empty,
  }), [remote, featured, empty]);

  const talentModel = useMemo(() => {
    const base = talentFromPayload(talentPayload) || {
      roleLeaders: { columns: [] },
      studioFootprint: { studios: [] },
      tasteSignals: { sortOptions: [] },
    };
    if (!featured?.source) return base;
    const key = `${featured.source}:${featured.personId}`;
    return {
      ...base,
      roleLeaders: {
        ...base.roleLeaders,
        columns: (base.roleLeaders?.columns || []).map(column => ({
          ...column,
          entries: column.entries.map(entry => ({ ...entry, selected: `${entry.source}:${entry.personId}` === key })),
        })),
      },
    };
  }, [talentPayload, featured]);

  const mediaOverviewModel = useMemo(() => ({
    items: remote?.overviews || [],
  }), [remote]);

  const comparisonModel = remote?.comparison && remote.comparison.rows ? remote.comparison : null;

  function retry() {
    setReloadKey(value => value + 1);
  }

  function refresh() {
    setRefreshing(true);
    setBannerHidden(false);
    if (remote?.rangeName) {
      transport.requestRefresh({ rangeName: remote.rangeName }).catch(failure => {
        console.warn('Statistics refresh could not be queued', failure);
      });
    }
    setReloadKey(value => value + 1);
  }

  function savePreferences(values) {
    setPrefsSaving(true);
    setPrefsError('');
    transport.saveDisplayPreferences(values).then(next => {
      setPrefs(next);
      setPrefsOpen(false);
      setRefreshing(true);
      setReloadKey(value => value + 1);
    }).catch(failure => {
      setPrefsError(failure?.message || 'The preferences could not be saved.');
    }).finally(() => setPrefsSaving(false));
  }

  function changeRange(option) {
    setRefreshing(true);
    if (option.value === 'custom') {
      setRangeRequest({ startDate: option.startDate, endDate: option.endDate });
      return;
    }
    setRangeRequest({ rangeName: option.value });
    // The web page remembers the last named range as the account default.
    transport.saveDefaultRange({ rangeName: option.value }).catch(failure => {
      console.warn('Statistics default range could not be saved', failure);
    });
  }

  function changeCompare(value) {
    setCompare(value);
    transport.saveCompareMode({ compareMode: value }).catch(failure => {
      console.warn('Statistics compare mode could not be saved', failure);
    });
  }

  function changeMediaTypes(next) {
    setSelectedTypes(next);
    transport.saveMediaTypes({ mediaTypes: next }).catch(failure => {
      console.warn('Statistics media types could not be saved', failure);
    });
  }

  // The server sorts the talent boards by the saved preference, so a sort
  // change saves it and reloads the section.
  function saveSort(save, sortBy) {
    save({ sortBy })
      .then(() => setTalentKey(value => value + 1))
      .catch(failure => console.warn('Statistics sort could not be saved', failure));
  }

  function selectPerson(entry) {
    if (!entry?.source || !entry?.personId) return;
    transport.selectFeaturedPerson({
      source: entry.source,
      personId: entry.personId,
      ...rangeRequest,
    }).then(result => {
      const next = featuredFromPerson(result?.featured_person);
      if (next) setFeaturedOverride(next);
    }).catch(failure => console.warn('Featured person could not be loaded', failure));
  }

  function openPerson(entry) {
    if (!entry?.source || !entry?.personId) return;
    navigate('People', {
      kind: 'person',
      source: entry.source,
      personId: entry.personId,
      slug: entry.personId,
    });
  }

  const prefsPalette = { ...palette, accentText: palette.onAccentStrong };
  const building = Boolean(remote?.building);
  return <Screen chrome={false} contentStyle={{ paddingTop: 24 }}>
    {server && prefs ? <StatisticsPreferencesButton palette={prefsPalette} onPress={() => setPrefsOpen(true)} /> : null}
    {server && !bannerHidden ? <StatisticsBanner building={building} refreshing={refreshing && !building}
      palette={prefsPalette} onDismiss={() => setBannerHidden(true)} /> : null}
    <StatisticsPreferencesModal open={prefsOpen} palette={prefsPalette} saving={prefsSaving} error={prefsError}
      values={prefs} choices={prefs?.display_choices} splitAvailable={Boolean(prefs?.stats_split_available)}
      onSave={savePreferences} onClose={() => setPrefsOpen(false)} />
    <StatisticsView
      model={model}
      comparison={comparisonModel}
      charts={chartModel}
      talent={talentModel}
      mediaOverviews={mediaOverviewModel}
      talentState={talentState}
      sections={['summary', 'charts', 'talent', 'overviews']}
      title={null}
      subtitle={null}
      labels={server ? { ...talentLabels, ...labels } : { ...labels, ...signedOutLabels }}
      palette={statisticsPalette}
      onChangeRange={changeRange}
      onChangeMediaTypes={changeMediaTypes}
      onCompareMode={changeCompare}
      onRefresh={refresh}
      onSelectHighlight={item => navigate('Detail', { item })}
      onRoleSortChange={sortBy => saveSort(transport.saveTopTalentSort, sortBy)}
      onStudioSortChange={sortBy => saveSort(transport.saveStudioSort, sortBy)}
      onTasteSortChange={sortBy => saveSort(transport.saveGenreSort, sortBy)}
      onOpenPerson={openPerson}
      onSelectPerson={selectPerson}
      onSelectItem={item => navigate('Detail', { item })}
      onRetry={retry} />
  </Screen>;
}
