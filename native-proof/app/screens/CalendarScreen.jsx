import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Linking } from 'react-native';
import { CalendarView } from '../../../frontend/pages/CalendarView';
import { CalendarLinks } from '../../../frontend/ui/CalendarLinks';
import { copyText } from '../../../frontend/ui/clipboard';
import { Screen } from '../components/Screen';
import { readCalendarPreferences, writeCalendarPreferences } from '../data/calendarPreferences';
import {
  calendarModelFromPayload,
  calendarOptionsFromEvents,
  calendarOptionsFromLinks,
  createCalendarTransport,
} from '../data/calendarTransport';
import CalendarSlot from '../surfaces/CalendarSlot';
import { useAccountDisplay } from '../data/accountDisplay';
import { getDatePreferences } from '../data/userDate';
import { palette } from '../theme';

// The web calendar's "today" is the server's calendar day, not the device's.
function serverToday() {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: getDatePreferences().timeZone || 'UTC', year: 'numeric', month: 'numeric', day: 'numeric',
  }).formatToParts(new Date());
  const pick = type => Number(parts.find(part => part.type === type)?.value);
  return new Date(pick('year'), pick('month') - 1, pick('day'));
}

function currentMonth() {
  const now = serverToday();
  return { month: now.getMonth() + 1, year: now.getFullYear() };
}

function openUrl(url) {
  return Linking.openURL(url);
}

export default function CalendarScreen({ navigate }) {
  const display = useAccountDisplay();
  const [transport] = useState(() => createCalendarTransport());
  const server = transport.mode === 'server';
  const userId = useRef(null);
  const preferences = useRef({ filters: null });
  const [links, setLinks] = useState(null);
  const [linksSessionRequired, setLinksSessionRequired] = useState(false);
  const [linksReady, setLinksReady] = useState(!server);
  const [filters, setFilters] = useState(null);
  const [weekStart, setWeekStart] = useState('monday');
  const [hydrated, setHydrated] = useState(!server);
  const [actionNote, setActionNote] = useState('');
  const [period, setPeriod] = useState(currentMonth);
  const [payload, setPayload] = useState(null);
  const [loading, setLoading] = useState(server);
  const [loadError, setLoadError] = useState('');
  const [reloadToken, setReloadToken] = useState(0);

  // The links payload is the server's vocabulary (types, statuses, release
  // types, week start) plus the account's real subscription URLs.
  useEffect(() => {
    if (!server) return undefined;
    let active = true;
    transport.readLinks()
      .then(next => {
        if (!active) return null;
        userId.current = next?.user_id ?? null;
        setLinks(next);
        setWeekStart(next?.week_start_day === 'sunday' ? 'sunday' : 'monday');
        return readCalendarPreferences(userId.current);
      })
      .catch(error => {
        if (active && error?.status === 403) setLinksSessionRequired(true);
        return null;
      })
      .then(stored => {
        if (!active) return;
        preferences.current = { filters: stored?.filters || null };
        setFilters(stored?.filters || null);
        setLinksReady(true);
        setHydrated(true);
      });
    return () => { active = false; };
  }, [transport, server]);

  useEffect(() => {
    if (!server || !hydrated) return undefined;
    let active = true;
    setLoading(true);
    setLoadError('');
    transport.readAll({ month: period.month, year: period.year })
      .then(result => {
        if (!active) return;
        setPayload(result);
        setLoading(false);
      })
      .catch(error => {
        if (!active) return;
        setPayload(null);
        setLoadError(error?.message || 'Calendar could not be loaded from the server.');
        setLoading(false);
      });
    return () => { active = false; };
  }, [transport, server, hydrated, period, reloadToken]);

  const model = useMemo(() => (payload
    ? calendarModelFromPayload(payload, { month: period.month, year: period.year, weekStart, today: serverToday() })
    : null), [payload, period, weekStart, display.loaded]);
  const options = useMemo(() => {
    if (!model) return null;
    return (links && calendarOptionsFromLinks(links, model.releases))
      || calendarOptionsFromEvents(model.releases);
  }, [links, model]);

  function savePreferences(patch) {
    const next = { ...preferences.current, ...patch };
    preferences.current = next;
    writeCalendarPreferences(next, userId.current);
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
    if (target === 'previous') moveMonth(-1);
    else if (target === 'next') moveMonth(1);
    else if (target === 'today') {
      setPeriod(currentMonth());
      setActionNote('');
    }
  }

  function handleMenuAction({ key, value }) {
    if (key === 'weekStart') {
      const previous = weekStart;
      setWeekStart(value);
      transport.saveWeekStart(value).catch(error => {
        setWeekStart(previous);
        setActionNote(error?.message || 'Could not save the week start.');
      });
      return;
    }
    if (key === 'today') {
      setPeriod(currentMonth());
      setActionNote('');
      return;
    }
    if (key === 'fetch') {
      if (!server) {
        setActionNote('Sign in to your Floppy server to fetch new releases.');
        return;
      }
      setActionNote('Fetching new releases…');
      transport.fetchReleases()
        .then(() => {
          setActionNote('The task to refresh upcoming releases has been queued.');
          setReloadToken(current => current + 1);
        })
        .catch(error => setActionNote(error?.message || 'Could not fetch new releases.'));
      return;
    }
    if (key === 'download') {
      if (links?.release_base_url) {
        openUrl(links.release_base_url).catch(() => setActionNote('Could not open the calendar download.'));
      } else {
        setActionNote(linksSessionRequired ? 'Sign in with your username and password to manage this.' : 'No calendar link is available.');
      }
    }
  }

  const localNotice = server ? '' : 'Sign in to your Floppy server to see the calendar.';
  const notice = loadError || actionNote || localNotice;
  const empty = server && !loading && Boolean(model?.empty);
  const linksProps = options?.linksProps;

  return <Screen chrome={false} contentStyle={{ paddingTop: 24 }}>
    <CalendarView
      subtitle={null}
      palette={palette}
      loading={server && (!hydrated || !linksReady || loading)}
      empty={empty}
      notice={notice}
      onRetry={loadError ? () => setReloadToken(current => current + 1) : undefined}
      calendar={model && options ? <CalendarSlot
        model={model}
        options={options}
        regionUnset={options.regionUnset}
        initialFilters={filters || undefined}
        weekStart={weekStart}
        onNavigate={handleNavigate}
        onOpenRelease={release => navigate('Detail', { item: release })}
        onFiltersChange={next => {
          setFilters(next);
          savePreferences({ filters: next });
        }}
        onMenuAction={handleMenuAction} /> : null}
      links={linksProps || linksSessionRequired ? <CalendarLinks
        {...linksProps}
        sessionRequired={linksSessionRequired}
        palette={{
          ...palette,
          surfaceDim: palette.surfaceStrong,
          accentText: palette.accentContrast,
        }}
        onCopyLink={async url => {
          if (!(await copyText(url))) throw new Error('Could not copy the link.');
        }}
        onDownload={url => openUrl(url).catch(() => setActionNote('Could not open the calendar link.'))} /> : null} />
  </Screen>;
}
