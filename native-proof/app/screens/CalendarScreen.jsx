import React, { useEffect, useRef, useState } from 'react';
import { CalendarView } from '../../../frontend/pages/CalendarView';
import { CalendarLinks } from '../../../frontend/ui/CalendarLinks';
import { Screen } from '../components/Screen';
import { readCalendarPreferences, writeCalendarPreferences } from '../data/calendarPreferences';
import {
  calendarModelFromPayload,
  createCalendarTransport,
} from '../data/calendarTransport';
import CalendarSlot from '../surfaces/CalendarSlot';
import { palette } from '../theme';

const defaultWeekStart = 'monday';

const releaseMediaTypes = [
  { value: 'tv', label: 'TV Shows' },
  { value: 'season', label: 'TV Seasons' },
  { value: 'movie', label: 'Movies' },
  { value: 'anime', label: 'Anime' },
  { value: 'book', label: 'Books' },
  { value: 'game', label: 'Games' },
  { value: 'podcast', label: 'Podcasts' },
];

const historyMediaTypes = [
  { value: 'tv', label: 'TV Shows' },
  { value: 'movie', label: 'Movies' },
  { value: 'anime', label: 'Anime' },
  { value: 'manga', label: 'Manga' },
  { value: 'game', label: 'Games' },
  { value: 'book', label: 'Books' },
  { value: 'comic', label: 'Comics' },
  { value: 'boardgame', label: 'Board Games' },
  { value: 'music', label: 'Music' },
  { value: 'podcast', label: 'Podcasts' },
  { value: 'video', label: 'Videos' },
];

const historyDefaultTypes = historyMediaTypes
  .filter((item) => !['music', 'podcast', 'video'].includes(item.value))
  .map((item) => item.value);

const statuses = [
  { value: 'Planning', label: 'Planning' },
  { value: 'In progress', label: 'In Progress' },
  { value: 'Paused', label: 'Paused' },
  { value: 'Completed', label: 'Completed' },
  { value: 'Dropped', label: 'Dropped' },
];

const releaseTypes = [
  { value: 'digital', label: 'Digital' },
  { value: 'physical', label: 'Physical' },
];

const calendarLinkPalette = {
  ...palette,
  surfaceDim: palette.surfaceStrong,
  accentText: '#ffffff',
  link: '#818cf8',
};

function currentMonth() {
  const now = new Date();
  return { month: now.getMonth() + 1, year: now.getFullYear() };
}

export default function CalendarScreen({ navigate }) {
  const [transport] = useState(() => createCalendarTransport());
  const preferences = useRef({ filters: null, weekStart: defaultWeekStart });
  const [filters, setFilters] = useState(null);
  const [weekStart, setWeekStart] = useState(defaultWeekStart);
  const [hydrated, setHydrated] = useState(false);
  const [actionNote, setActionNote] = useState('');
  const [period, setPeriod] = useState(currentMonth);
  const [model, setModel] = useState(null);
  const [loading, setLoading] = useState(transport.mode === 'server');
  const [loadError, setLoadError] = useState('');
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let active = true;
    readCalendarPreferences().then((stored) => {
      if (!active) {
        return;
      }
      const next = {
        filters: stored?.filters || null,
        weekStart: stored?.weekStart === 'sunday' ? 'sunday' : defaultWeekStart,
      };
      preferences.current = next;
      setFilters(next.filters);
      setWeekStart(next.weekStart);
      setHydrated(true);
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (transport.mode !== 'server' || !hydrated) {
      return undefined;
    }
    let active = true;
    setLoading(true);
    setLoadError('');
    transport.readAll({ month: period.month, year: period.year })
      .then(payload => {
        if (!active) return;
        setModel(calendarModelFromPayload(payload, {
          month: period.month,
          year: period.year,
          weekStart,
        }));
        setLoading(false);
      })
      .catch(error => {
        if (!active) return;
        setModel(null);
        setLoadError(error?.message || 'Calendar could not be loaded from the server.');
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [transport, hydrated, period, weekStart, reloadToken]);

  function savePreferences(patch) {
    const next = { ...preferences.current, ...patch };
    preferences.current = next;
    writeCalendarPreferences(next);
  }

  function handleFiltersChange(next) {
    setFilters(next);
    savePreferences({ filters: next });
  }

  function moveMonth(delta) {
    setPeriod(current => {
      const index = current.month - 1 + delta;
      return {
        month: ((index + 12) % 12) + 1,
        year: current.year + Math.floor(index / 12),
      };
    });
    setActionNote('');
  }

  function handleNavigate(target) {
    if (target === 'previous') {
      moveMonth(-1);
      return;
    }
    if (target === 'next') {
      moveMonth(1);
      return;
    }
    if (target === 'today') {
      setPeriod(currentMonth());
      setActionNote('');
    }
  }

  function handleMenuAction({ key, value }) {
    if (key === 'weekStart') {
      setWeekStart(value);
      savePreferences({ weekStart: value });
      setActionNote(`Week starts on ${value === 'sunday' ? 'Sunday' : 'Monday'}.`);
      return;
    }
    if (key === 'today') {
      setPeriod(currentMonth());
      setActionNote('');
      return;
    }
    if (key === 'fetch') {
      if (transport.mode !== 'server') {
        setActionNote('Sign in to your Floppy server to fetch new releases.');
        return;
      }
      setActionNote('Fetching new releases…');
      transport.fetchReleases()
        .then(() => {
          setActionNote('Release fetch queued on the Django server.');
          setReloadToken(current => current + 1);
        })
        .catch(error => setActionNote(error.message || 'Could not fetch new releases.'));
      return;
    }
    if (key === 'download') {
      setActionNote('Calendar downloads use the subscription link below.');
    }
  }

  const localNotice = transport.mode === 'local'
    ? 'Sign in to your Floppy server to see the calendar.'
    : '';
  const notice = loadError || actionNote || localNotice;
  const empty = transport.mode === 'server' && !loading && Boolean(model?.empty);

  return <Screen chrome={false}>
    <CalendarView
      palette={palette}
      loading={transport.mode === 'server' && (!hydrated || loading)}
      empty={empty}
      notice={notice}
      calendar={model ? <CalendarSlot
        model={model}
        initialFilters={filters || undefined}
        weekStart={weekStart}
        onNavigate={handleNavigate}
        onOpenRelease={() => navigate('Detail')}
        onFiltersChange={handleFiltersChange}
        onMenuAction={handleMenuAction} /> : null}
      links={<CalendarLinks
        releaseMediaTypes={releaseMediaTypes}
        historyMediaTypes={historyMediaTypes}
        statuses={statuses}
        releaseTypes={releaseTypes}
        initialHistoryMediaTypes={historyDefaultTypes}
        releaseBaseUrl="https://app.floppy.example/calendar/demo-token.ics"
        historyBaseUrl="https://app.floppy.example/calendar/history/demo-token.ics"
        palette={calendarLinkPalette} />} />
  </Screen>;
}