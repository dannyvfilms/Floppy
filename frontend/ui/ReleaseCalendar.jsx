import React, { useMemo, useState } from 'react';
import {
  Image,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { Badge } from './Badge';

const DEFAULT_PALETTE = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  surfaceHover: '#3f3f46',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentText: '#ffffff',
  link: '#818cf8',
  danger: '#ef4444',
  overlay: 'rgba(24, 24, 27, 0.78)',
};

const DEFAULT_LABELS = {
  filters: 'Filters',
  all: 'All',
  none: 'None',
  mediaTypes: 'Media Types',
  status: 'Status',
  movieReleaseDates: 'Movie Release Dates',
  clearAll: 'Clear all filters',
  close: 'Close',
  agenda: 'Agenda',
  closeDay: 'Close day details',
  noDayReleases: 'No releases scheduled for this day.',
  noFilteredReleases: 'No releases for selected media types.',
  today: 'Today',
  release: 'release',
  releases: 'releases',
  viewMonth: 'Month',
  viewList: 'List',
  previousMonth: 'Previous month',
  nextMonth: 'Next month',
  filterCalendar: 'Filter calendar by media type',
};

const MENU_LABELS = {
  menu: 'Calendar Actions',
  today: 'Go to Today',
  fetch: 'Fetch New Releases',
  download: 'Download Calendar',
  weekStart: 'Week starts on',
  monday: 'Monday',
  sunday: 'Sunday',
};

function groupFor(mediaType) {
  return mediaType === 'season' ? 'tv' : mediaType;
}

function compareText(left, right) {
  return String(left || '').localeCompare(String(right || ''), undefined, {
    sensitivity: 'base',
    numeric: true,
  });
}

function compareReleases(left, right) {
  const unknownLeft = left.unknownTime ? 1 : 0;
  const unknownRight = right.unknownTime ? 1 : 0;
  if (unknownLeft !== unknownRight) {
    return unknownLeft - unknownRight;
  }
  if (!unknownLeft && left.sortTime !== right.sortTime) {
    return left.sortTime - right.sortTime;
  }
  return compareText(left.title, right.title);
}

function valuesForGroup(mediaTypes, group) {
  if (group === 'all') {
    return mediaTypes.map((item) => item.value);
  }
  return mediaTypes
    .filter(
      (item) =>
        item.value === group || (group === 'tv' && item.value === 'season'),
    )
    .map((item) => item.value);
}

function releasePasses(
  release,
  selectedTypes,
  selectedStatusesByType,
  selectedReleaseTypes,
) {
  if (!selectedTypes.includes(release.mediaType)) {
    return false;
  }
  if (release.releaseType && !selectedReleaseTypes.includes(release.releaseType)) {
    return false;
  }
  if (release.status) {
    const statuses = selectedStatusesByType[release.mediaType] || [];
    if (!statuses.includes(release.status)) {
      return false;
    }
  }
  return true;
}

export function ReleaseCalendar({
  month,
  year,
  monthName,
  weekdayHeaders = [],
  weeks = [],
  daysInMonth = [],
  dayLabels = {},
  today,
  selectedDay,
  view: initialView = 'grid',
  releases = {},
  mediaTypes = [],
  releaseTypes = [],
  statusesByType = {},
  initialFilters,
  navigation = {},
  menu,
  labels,
  palette,
  onNavigate,
  onOpenRelease,
  onViewChange,
  onFiltersChange,
  onMenuAction,
}) {
  const { width } = useWindowDimensions();
  const compact = width < 768;
  const colors = { ...DEFAULT_PALETTE, ...(palette || {}) };
  const copy = { ...DEFAULT_LABELS, ...(labels || {}) };
  const menuCopy = { ...MENU_LABELS, ...(menu?.labels || {}) };
  const styles = useMemo(() => createStyles(colors, compact), [colors, compact]);

  const allTypes = useMemo(
    () => mediaTypes.map((item) => item.value),
    [mediaTypes],
  );
  const allStatusesByType = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(statusesByType).map(([type, statuses]) => [
          type,
          statuses.map((status) => status.value),
        ]),
      ),
    [statusesByType],
  );
  const allReleaseTypes = useMemo(
    () => releaseTypes.map((item) => item.value),
    [releaseTypes],
  );

  const [selectedTypes, setSelectedTypes] = useState(() =>
    Array.isArray(initialFilters?.selectedTypes)
      ? initialFilters.selectedTypes.filter((value) => allTypes.includes(value))
      : allTypes,
  );
  const [selectedStatusesByType, setSelectedStatusesByType] = useState(() =>
    initialFilters?.selectedStatusesByType &&
    typeof initialFilters.selectedStatusesByType === 'object'
      ? Object.fromEntries(
          Object.entries(allStatusesByType).map(([type, statuses]) => {
            const saved = initialFilters.selectedStatusesByType[type];
            return [
              type,
              Array.isArray(saved)
                ? saved.filter((status) => statuses.includes(status))
                : statuses,
            ];
          }),
        )
      : allStatusesByType,
  );
  const [selectedReleaseTypes, setSelectedReleaseTypes] = useState(() =>
    Array.isArray(initialFilters?.selectedReleaseTypes)
      ? initialFilters.selectedReleaseTypes.filter((value) =>
          allReleaseTypes.includes(value),
        )
      : allReleaseTypes,
  );
  const [activeDay, setActiveDay] = useState(() => {
    const value = Number(selectedDay);
    return daysInMonth.includes(value) ? value : daysInMonth[0] || 1;
  });
  const [view, setView] = useState(initialView === 'list' ? 'list' : 'grid');
  const [agendaOpen, setAgendaOpen] = useState(true);
  const [filterOpen, setFilterOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [weekStart, setWeekStart] = useState(menu?.weekStart || 'monday');

  const visibleByDay = useMemo(() => {
    const result = {};
    Object.entries(releases).forEach(([day, list]) => {
      result[day] = list.filter((release) =>
        releasePasses(
          release,
          selectedTypes,
          selectedStatusesByType,
          selectedReleaseTypes,
        ),
      );
    });
    return result;
  }, [releases, selectedTypes, selectedStatusesByType, selectedReleaseTypes]);

  const selectedReleases = visibleByDay[String(activeDay)] || [];
  const tagCounts = { all: selectedReleases.length };
  selectedReleases.forEach((release) => {
    const group = groupFor(release.mediaType);
    tagCounts[group] = (tagCounts[group] || 0) + 1;
  });

  function notifyFilters(next) {
    onFiltersChange?.(next);
  }

  function commitFilters(nextTypes, nextStatuses, nextReleaseTypes) {
    setSelectedTypes(nextTypes);
    setSelectedStatusesByType(nextStatuses);
    setSelectedReleaseTypes(nextReleaseTypes);
    notifyFilters({
      selectedTypes: nextTypes,
      selectedStatusesByType: nextStatuses,
      selectedReleaseTypes: nextReleaseTypes,
    });
  }

  function toggleType(value) {
    const nextTypes = selectedTypes.includes(value)
      ? selectedTypes.filter((type) => type !== value)
      : [...selectedTypes, value];
    commitFilters(nextTypes, selectedStatusesByType, selectedReleaseTypes);
  }

  function toggleStatus(mediaType, value) {
    const current = selectedStatusesByType[mediaType] || [];
    const statuses = current.includes(value)
      ? current.filter((status) => status !== value)
      : [...current, value];
    const nextStatuses = {
      ...selectedStatusesByType,
      [mediaType]: statuses,
    };
    commitFilters(selectedTypes, nextStatuses, selectedReleaseTypes);
  }

  function toggleReleaseType(value) {
    const nextReleaseTypes = selectedReleaseTypes.includes(value)
      ? selectedReleaseTypes.filter((type) => type !== value)
      : [...selectedReleaseTypes, value];
    commitFilters(selectedTypes, selectedStatusesByType, nextReleaseTypes);
  }

  function clearFilters() {
    const statuses = Object.fromEntries(
      Object.entries(allStatusesByType).map(([type, values]) => [
        type,
        [...values],
      ]),
    );
    commitFilters([...allTypes], statuses, [...allReleaseTypes]);
  }

  function selectGroup(group) {
    const nextTypes = valuesForGroup(mediaTypes, group);
    commitFilters(nextTypes, selectedStatusesByType, selectedReleaseTypes);
  }

  function isGroupSelected(group) {
    const values = valuesForGroup(mediaTypes, group);
    return (
      values.length > 0 &&
      values.length === selectedTypes.length &&
      values.every((value) => selectedTypes.includes(value))
    );
  }

  function hasPartialStatus() {
    return selectedTypes.some((type) => {
      const statuses = allStatusesByType[type] || [];
      const selected = selectedStatusesByType[type] || [];
      return statuses.length > 0 && selected.length !== statuses.length;
    });
  }

  function summaryForTypes() {
    if (!allTypes.length) {
      return copy.none;
    }
    if (selectedTypes.length === allTypes.length) {
      return copy.all;
    }
    if (!selectedTypes.length) {
      return copy.none;
    }
    if (selectedTypes.length === 1) {
      const match = mediaTypes.find((item) => item.value === selectedTypes[0]);
      return match ? match.label : copy.filters;
    }
    return `${selectedTypes.length}/${allTypes.length}`;
  }

  function summaryForReleaseTypes() {
    const total = allReleaseTypes.length;
    const selected = selectedReleaseTypes.length;
    if (!total || selected === total) {
      return copy.all;
    }
    if (!selected) {
      return copy.none;
    }
    const match = releaseTypes.find((item) => item.value === selectedReleaseTypes[0]);
    return selected === 1 && match ? match.label : `${selected}/${total}`;
  }

  function filterSummary() {
    const parts = [summaryForTypes()];
    if (hasPartialStatus()) {
      parts.push(copy.status);
    }
    if (selectedReleaseTypes.length < allReleaseTypes.length) {
      parts.push(summaryForReleaseTypes());
    }
    return parts.join(' · ');
  }

  function navigate(url) {
    if (url) {
      onNavigate?.(url);
    }
  }

  function goToToday() {
    if (navigation.today && onNavigate) {
      navigate(navigation.today);
      return;
    }
    if (today) {
      setActiveDay(today.day);
      setView('grid');
    }
  }

  function changeView(nextView) {
    if (nextView === view) {
      return;
    }
    if (onViewChange) {
      onViewChange(nextView);
      return;
    }
    setView(nextView);
  }

  function openRelease(release) {
    if (onOpenRelease) {
      onOpenRelease(release);
      return;
    }
    navigate(release.href);
  }

  function selectDay(day) {
    setActiveDay(day);
    setAgendaOpen(true);
  }

  function menuAction(key, value) {
    setMenuOpen(false);
    if (key === 'weekStart') {
      setWeekStart(value);
      onMenuAction?.({ key, value });
      return;
    }
    if (key === 'today') {
      if (onMenuAction) {
        onMenuAction({ key });
      } else {
        goToToday();
      }
      return;
    }
    if (key === 'download') {
      if (onMenuAction) {
        onMenuAction({ key });
      } else {
        navigate(menu?.urls?.download);
      }
      return;
    }
    onMenuAction?.({ key });
  }

  const badgePalette = {
    outline: {
      color: colors.textSecondary,
      borderColor: colors.border,
      borderWidth: 1,
    },
    indigo: {
      color: colors.accentText,
      backgroundColor: colors.accentStrong,
    },
  };

  function mediaLabelForGroup(group) {
    const match = mediaTypes.find((item) => item.value === group);
    return match ? match.shortLabel || match.label : group;
  }

  function agendaGroups() {
    const groups = new Map();
    selectedReleases.forEach((release) => {
      const group = groupFor(release.mediaType);
      if (!groups.has(group)) {
        groups.set(group, []);
      }
      groups.get(group).push(release);
    });
    return [...groups.entries()]
      .map(([group, items]) => ({
        group,
        label: mediaLabelForGroup(group),
        items: [...items].sort(compareReleases),
      }))
      .sort(
        (left, right) =>
          right.items.length - left.items.length ||
          compareText(left.label, right.label),
      );
  }

  const listDays = Object.keys(visibleByDay)
    .map(Number)
    .filter((day) => (visibleByDay[String(day)] || []).length > 0)
    .sort((left, right) => left - right);

  const tagTypes = mediaTypes.filter(
    (item) => item.value !== 'season' && (tagCounts[item.value] || 0) > 0,
  );

  return <View style={styles.root}>
    <View style={styles.toolbar}>
      <View style={styles.monthNavigation}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={copy.previousMonth}
          onPress={() => navigate(navigation.previous)}
          style={({ pressed }) => [styles.navButton, pressed && styles.pressed]}>
          <Text style={styles.navText}>‹</Text>
        </Pressable>
        <Text style={styles.monthTitle}>{monthName} {year}</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={copy.nextMonth}
          onPress={() => navigate(navigation.next)}
          style={({ pressed }) => [styles.navButton, pressed && styles.pressed]}>
          <Text style={styles.navText}>›</Text>
        </Pressable>
      </View>

      <View style={styles.toolbarActions}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`${copy.filters}: ${filterSummary()}`}
          onPress={() => setFilterOpen(true)}
          style={({ pressed }) => [styles.toolbarButton, pressed && styles.pressed]}>
          <Text numberOfLines={1} style={styles.toolbarButtonText}>{filterSummary()}</Text>
        </Pressable>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={menuCopy.today}
          onPress={goToToday}
          style={({ pressed }) => [styles.toolbarButton, pressed && styles.pressed]}>
          <Text style={styles.toolbarButtonText}>{menuCopy.today}</Text>
        </Pressable>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={menuCopy.menu}
          accessibilityState={{ expanded: menuOpen }}
          onPress={() => setMenuOpen(true)}
          style={({ pressed }) => [styles.menuButton, pressed && styles.pressed]}>
          <Text style={styles.menuGlyph}>⚙</Text>
        </Pressable>
      </View>
    </View>

    <View style={styles.viewSwitch} accessibilityRole="tablist">
      {['grid', 'list'].map((item) => <Pressable
        key={item}
        accessibilityRole="tab"
        accessibilityState={{ selected: view === item }}
        accessibilityLabel={item === 'grid' ? copy.viewMonth : copy.viewList}
        onPress={() => changeView(item)}
        style={({ pressed }) => [
          styles.viewTab,
          view === item && styles.viewTabSelected,
          pressed && styles.pressed,
        ]}>
        <Text style={[
          styles.viewTabText,
          view === item && styles.viewTabTextSelected,
        ]}>{item === 'grid' ? copy.viewMonth : copy.viewList}</Text>
      </Pressable>)}
    </View>

    {view === 'list' ? <View style={styles.listStack}>
      {listDays.map((day) => {
        const dayReleases = [...(visibleByDay[String(day)] || [])].sort(compareReleases);
        const isToday = Boolean(
          today &&
          day === today.day &&
          month === today.month &&
          year === today.year,
        );
        return <View key={day} style={styles.listDayCard}>
          <View style={[styles.listDayHeader, isToday && styles.listDayHeaderToday]}>
            <Text style={styles.listDayTitle}>
              {dayLabels[String(day)]}, {monthName} {day}
            </Text>
            {isToday ? <Badge label={copy.today} size="sm" tone="indigo" palette={badgePalette} /> : null}
          </View>
          <View style={styles.listDayBody}>
            {dayReleases.map((release) => <ReleaseRow
              key={release.id}
              release={release}
              copy={copy}
              colors={colors}
              styles={styles}
              badgePalette={badgePalette}
              showMedia
              onPress={() => openRelease(release)} />)}
          </View>
        </View>;
      })}
      {listDays.length === 0 ? <View style={styles.emptyCard}>
        <Text style={styles.emptyText}>{copy.noFilteredReleases}</Text>
      </View> : null}
    </View> : <View style={[styles.layout, !compact && agendaOpen && styles.layoutWithAgenda]}>
      <View style={styles.monthCard}>
        <View style={styles.weekHeaderRow}>
          {weekdayHeaders.map((header) => <Text key={header} style={styles.weekHeader}>{header}</Text>)}
        </View>
        <View style={styles.weeks}>
          {weeks.map((week, weekIndex) => <View key={weekIndex} style={styles.weekRow}>
            {week.map((day, dayIndex) => {
              if (day === 0) {
                return <View key={`${weekIndex}-${dayIndex}`} style={[styles.dayCell, styles.blankDay]} />;
              }
              const dayReleases = visibleByDay[String(day)] || [];
              const isSelected = day === activeDay;
              const isToday = Boolean(
                today &&
                day === today.day &&
                month === today.month &&
                year === today.year,
              );
              const images = dayReleases.slice(0, 4);
              const tileSize = images.length === 1 ? 'single' : images.length === 2 ? 'double' : 'grid';
              return <Pressable
                key={`${weekIndex}-${dayIndex}`}
                accessibilityRole="button"
                accessibilityLabel={`${monthName} ${day}`}
                accessibilityState={{ selected: isSelected }}
                onPress={() => selectDay(day)}
                style={({ pressed }) => [
                  styles.dayCell,
                  isSelected && styles.dayCellSelected,
                  isToday && styles.dayCellToday,
                  pressed && styles.pressed,
                ]}>
                {titleArtwork(images, tileSize, styles)}
                <View style={[styles.dayNumber, isToday && styles.dayNumberToday]}>
                  <Text style={styles.dayNumberText}>{day}</Text>
                </View>
                {dayReleases.length > 4 ? <View style={styles.moreBadge}>
                  <Text style={styles.moreText}>+{dayReleases.length - 4}</Text>
                </View> : null}
              </Pressable>;
            })}
          </View>)}
        </View>
      </View>

      {agendaOpen ? <View style={styles.agendaCard}>
        <View style={styles.agendaHeader}>
          <View style={styles.agendaHeading}>
            <Text style={styles.agendaTitle}>
              {dayLabels[String(activeDay)] ? `${monthName} ${activeDay}, ${year}` : copy.agenda}
            </Text>
            <Text style={styles.agendaCount}>
              {selectedReleases.length} {selectedReleases.length === 1 ? copy.release : copy.releases}
            </Text>
          </View>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={copy.closeDay}
            onPress={() => setAgendaOpen(false)}
            style={({ pressed }) => [styles.agendaClose, pressed && styles.pressed]}>
            <Text style={styles.agendaCloseText}>×</Text>
          </Pressable>
        </View>

        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.tagRow}
          accessibilityLabel={copy.filterCalendar}>
          <FilterChip
            label={`${copy.all} ${tagCounts.all || 0}`}
            selected={isGroupSelected('all')}
            onPress={() => selectGroup('all')}
            styles={styles} />
          {tagTypes.map((item) => <FilterChip
            key={item.value}
            label={`${item.shortLabel || item.label} ${tagCounts[item.value] || 0}`}
            selected={isGroupSelected(item.value)}
            onPress={() => selectGroup(item.value)}
            styles={styles} />)}
        </ScrollView>

        <View style={styles.agendaBody}>
          {selectedReleases.length === 0 ? <View style={styles.emptyCard}>
            <Text style={styles.emptyText}>{copy.noDayReleases}</Text>
          </View> : agendaGroups().map((section, index) => <View
            key={section.group}
            style={[styles.agendaSection, index > 0 && styles.agendaSectionDivider]}>
            <Text style={styles.agendaSectionTitle}>{section.label} ({section.items.length})</Text>
            {section.items.map((release) => <ReleaseRow
              key={release.id}
              release={release}
              copy={copy}
              colors={colors}
              styles={styles}
              badgePalette={badgePalette}
              onPress={() => openRelease(release)} />)}
          </View>)}
        </View>
      </View> : null}
    </View>}

    <Modal
      visible={filterOpen}
      transparent
      animationType="fade"
      onRequestClose={() => setFilterOpen(false)}>
      <View style={styles.overlay}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={copy.close}
          style={styles.backdrop}
          onPress={() => setFilterOpen(false)} />
        <View style={styles.sheet} accessibilityViewIsModal>
          <View style={styles.sheetHeader}>
            <Text style={styles.sheetTitle}>{copy.filters}</Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={copy.close}
              onPress={() => setFilterOpen(false)}
              style={({ pressed }) => [styles.sheetClose, pressed && styles.pressed]}>
              <Text style={styles.sheetCloseText}>×</Text>
            </Pressable>
          </View>
          <ScrollView style={styles.sheetBody} contentContainerStyle={styles.sheetContent}>
            <FilterSection title={copy.mediaTypes} styles={styles}>
              {mediaTypes.map((item) => <OptionRow
                key={item.value}
                label={item.label}
                checked={selectedTypes.includes(item.value)}
                onPress={() => toggleType(item.value)}
                styles={styles} />)}
            </FilterSection>

            {mediaTypes.map((item) => {
              const statuses = statusesByType[item.value] || [];
              if (!statuses.length) {
                return null;
              }
              return <FilterSection
                key={`${item.value}-status`}
                title={`${item.shortLabel || item.label} · ${copy.status}`}
                styles={styles}>
                {statuses.map((status) => <OptionRow
                  key={status.value}
                  label={status.inMonth ? `${status.label} •` : status.label}
                  checked={(selectedStatusesByType[item.value] || []).includes(status.value)}
                  onPress={() => toggleStatus(item.value, status.value)}
                  styles={styles} />)}
              </FilterSection>;
            })}

            {releaseTypes.length ? <FilterSection title={copy.movieReleaseDates} styles={styles}>
              {releaseTypes.map((item) => <OptionRow
                key={item.value}
                label={item.label}
                checked={selectedReleaseTypes.includes(item.value)}
                onPress={() => toggleReleaseType(item.value)}
                styles={styles} />)}
            </FilterSection> : null}

            <Pressable
              accessibilityRole="button"
              accessibilityLabel={copy.clearAll}
              onPress={clearFilters}
              style={({ pressed }) => [styles.clearAll, pressed && styles.pressed]}>
              <Text style={styles.clearAllText}>{copy.clearAll}</Text>
            </Pressable>
          </ScrollView>
        </View>
      </View>
    </Modal>

    <Modal
      visible={menuOpen}
      transparent
      animationType="fade"
      onRequestClose={() => setMenuOpen(false)}>
      <View style={styles.overlay}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={copy.close}
          style={styles.backdrop}
          onPress={() => setMenuOpen(false)} />
        <View style={styles.menuSheet} accessibilityViewIsModal>
          <View style={styles.sheetHeader}>
            <Text style={styles.sheetTitle}>{menuCopy.menu}</Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={copy.close}
              onPress={() => setMenuOpen(false)}
              style={({ pressed }) => [styles.sheetClose, pressed && styles.pressed]}>
              <Text style={styles.sheetCloseText}>×</Text>
            </Pressable>
          </View>
          <View style={styles.menuBody}>
            <MenuRow label={menuCopy.today} onPress={() => menuAction('today')} styles={styles} />
            <MenuRow label={menuCopy.fetch} onPress={() => menuAction('fetch')} styles={styles} />
            <MenuRow label={menuCopy.download} onPress={() => menuAction('download')} styles={styles} />
            <View style={styles.menuGroup}>
              <Text style={styles.menuGroupLabel}>{menuCopy.weekStart}</Text>
              <View style={styles.menuGroupActions}>
                {['monday', 'sunday'].map((value) => <Pressable
                  key={value}
                  accessibilityRole="button"
                  accessibilityState={{ selected: weekStart === value }}
                  accessibilityLabel={menuCopy[value]}
                  onPress={() => menuAction('weekStart', value)}
                  style={({ pressed }) => [
                    styles.menuChoice,
                    weekStart === value && styles.menuChoiceSelected,
                    pressed && styles.pressed,
                  ]}>
                  <Text style={[
                    styles.menuChoiceText,
                    weekStart === value && styles.menuChoiceTextSelected,
                  ]}>{menuCopy[value]}</Text>
                </Pressable>)}
              </View>
            </View>
          </View>
        </View>
      </View>
    </Modal>
  </View>;
}

function titleArtwork(images, tileSize, styles) {
  if (!images.length) {
    return null;
  }
  return <View style={styles.artworkGrid}>
    {images.map((release, index) => {
      const dimensions = tileSize === 'single'
        ? { width: '100%', height: '100%' }
        : tileSize === 'double'
          ? { width: '50%', height: '100%' }
          : { width: '50%', height: '50%' };
      if (!release.image) {
        return <View
          key={`${release.id}-${index}`}
          style={[dimensions, styles.artworkPlaceholder]}>
          <Text numberOfLines={2} style={styles.artworkPlaceholderText}>{release.title}</Text>
        </View>;
      }
      return <View key={`${release.id}-${index}`} style={dimensions}>
        <Image
          source={{ uri: release.image }}
          resizeMode="cover"
          accessible={false}
          style={styles.artworkImage} />
      </View>;
    })}
  </View>;
}

function FilterChip({ label, selected, onPress, styles }) {
  return <Pressable
    accessibilityRole="button"
    accessibilityLabel={label}
    accessibilityState={{ selected }}
    onPress={onPress}
    style={({ pressed }) => [
      styles.filterChip,
      selected && styles.filterChipSelected,
      pressed && styles.pressed,
    ]}>
    <Text style={[styles.filterChipText, selected && styles.filterChipTextSelected]}>{label}</Text>
  </Pressable>;
}

function FilterSection({ title, children, styles }) {
  return <View style={styles.filterSection}>
    <Text style={styles.filterSectionTitle}>{title}</Text>
    {children}
  </View>;
}

function OptionRow({ label, checked, onPress, styles }) {
  return <Pressable
    accessibilityRole="checkbox"
    accessibilityLabel={label}
    accessibilityState={{ checked }}
    onPress={onPress}
    style={({ pressed }) => [styles.optionRow, pressed && styles.pressed]}>
    <Text style={styles.optionLabel}>{label}</Text>
    <View style={[styles.checkbox, checked && styles.checkboxChecked]}>
      {checked ? <Text style={styles.checkboxMark}>✓</Text> : null}
    </View>
  </Pressable>;
}

function MenuRow({ label, onPress, styles }) {
  return <Pressable
    accessibilityRole="menuitem"
    accessibilityLabel={label}
    onPress={onPress}
    style={({ pressed }) => [styles.menuRow, pressed && styles.pressed]}>
    <Text style={styles.menuRowText}>{label}</Text>
  </Pressable>;
}

function ReleaseRow({
  release,
  copy,
  colors,
  styles,
  badgePalette,
  showMedia = false,
  onPress,
}) {
  return <Pressable
    accessibilityRole="link"
    accessibilityLabel={release.title}
    onPress={onPress}
    style={({ pressed }) => [styles.releaseRow, pressed && styles.pressed]}>
    {release.image ? <Image
      source={{ uri: release.image }}
      resizeMode="cover"
      accessible={false}
      style={styles.releaseArtwork} /> : <View style={[styles.releaseArtwork, styles.artworkPlaceholder]}>
      <Text numberOfLines={1} style={styles.artworkPlaceholderText}>{release.title}</Text>
    </View>}
    <View style={styles.releaseBody}>
      <Text numberOfLines={1} style={styles.releaseTitle}>{release.title}</Text>
      {release.cardLines.length ? <Text numberOfLines={1} style={styles.releaseLines}>
        {release.cardLines.join(' · ')}
      </Text> : null}
      <View style={styles.releaseMeta}>
        {showMedia ? <Badge label={release.mediaLabel} size="xs" tone="outline" palette={badgePalette} /> : null}
        <Text numberOfLines={1} style={[styles.releaseSubtitle, { color: colors.textMuted }]}>
          {release.subtitle || copy.noDayReleases}
        </Text>
      </View>
    </View>
  </Pressable>;
}

function createStyles(colors, compact) {
  return StyleSheet.create({
    root: { gap: 12 },
    toolbar: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 8,
    },
    monthNavigation: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      backgroundColor: colors.surfaceStrong,
      borderRadius: 8,
      padding: 4,
    },
    navButton: {
      minWidth: 32,
      minHeight: 32,
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: 6,
    },
    navText: { color: colors.textSecondary, fontSize: 22, lineHeight: 24 },
    monthTitle: {
      color: colors.text,
      fontSize: compact ? 14 : 17,
      fontWeight: '700',
      textAlign: 'center',
      minWidth: compact ? 120 : 160,
      paddingHorizontal: 6,
    },
    toolbarActions: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      alignItems: 'center',
      gap: 6,
    },
    toolbarButton: {
      minHeight: 36,
      maxWidth: compact ? 190 : 240,
      paddingHorizontal: 12,
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: 8,
      borderWidth: 1,
      borderColor: colors.border,
      backgroundColor: colors.surfaceStrong,
    },
    toolbarButtonText: { color: colors.textSecondary, fontSize: 13, fontWeight: '600' },
    menuButton: {
      width: 36,
      height: 36,
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: 8,
      borderWidth: 1,
      borderColor: colors.border,
      backgroundColor: colors.surfaceStrong,
    },
    menuGlyph: { color: colors.textSecondary, fontSize: 16 },
    pressed: { opacity: 0.72 },
    viewSwitch: {
      flexDirection: 'row',
      alignSelf: 'flex-start',
      gap: 4,
      padding: 4,
      borderRadius: 8,
      backgroundColor: colors.surfaceStrong,
    },
    viewTab: {
      minHeight: 32,
      paddingHorizontal: 12,
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: 6,
    },
    viewTabSelected: { backgroundColor: colors.accentStrong },
    viewTabText: { color: colors.textSecondary, fontSize: 13, fontWeight: '600' },
    viewTabTextSelected: { color: colors.accentText },
    layout: { gap: 12 },
    layoutWithAgenda: { flexDirection: 'row', alignItems: 'flex-start' },
    monthCard: {
      flex: 1,
      minWidth: 0,
      backgroundColor: colors.surface,
      borderRadius: 10,
      padding: compact ? 8 : 16,
      gap: 8,
    },
    weekHeaderRow: { flexDirection: 'row', gap: 4 },
    weekHeader: {
      flex: 1,
      textAlign: 'center',
      color: colors.textMuted,
      fontSize: compact ? 10 : 12,
      fontWeight: '600',
      paddingVertical: 2,
    },
    weeks: { gap: 4 },
    weekRow: { flexDirection: 'row', gap: 4 },
    dayCell: {
      flex: 1,
      minWidth: 0,
      aspectRatio: compact ? 1 : 0.75,
      borderRadius: 8,
      overflow: 'hidden',
      backgroundColor: colors.surfaceMuted,
      borderWidth: 1,
      borderColor: 'transparent',
    },
    blankDay: { backgroundColor: colors.surfaceStrong, opacity: 0.35 },
    dayCellSelected: { borderColor: colors.accent },
    dayCellToday: { borderColor: colors.accentStrong },
    artworkGrid: {
      flex: 1,
      flexDirection: 'row',
      flexWrap: 'wrap',
    },
    artworkImage: { width: '100%', height: '100%' },
    artworkPlaceholder: {
      backgroundColor: colors.surfaceStrong,
      alignItems: 'center',
      justifyContent: 'center',
      padding: 4,
    },
    artworkPlaceholderText: {
      color: colors.textMuted,
      fontSize: 10,
      textAlign: 'center',
    },
    dayNumber: {
      position: 'absolute',
      top: 4,
      right: 4,
      minWidth: 20,
      paddingHorizontal: 4,
      paddingVertical: 1,
      borderRadius: 4,
      backgroundColor: 'rgba(0, 0, 0, 0.72)',
      alignItems: 'center',
    },
    dayNumberToday: { backgroundColor: colors.accentStrong },
    dayNumberText: { color: '#ffffff', fontSize: 11, fontWeight: '700' },
    moreBadge: {
      position: 'absolute',
      bottom: 4,
      right: 4,
      paddingHorizontal: 4,
      paddingVertical: 1,
      borderRadius: 4,
      backgroundColor: colors.surfaceStrong,
    },
    moreText: { color: colors.textMuted, fontSize: 10, fontWeight: '700' },
    agendaCard: {
      width: compact ? '100%' : 340,
      backgroundColor: colors.surface,
      borderRadius: 10,
      overflow: 'hidden',
    },
    agendaHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 8,
      paddingHorizontal: 12,
      paddingVertical: 10,
      backgroundColor: colors.surfaceStrong,
    },
    agendaHeading: { flexShrink: 1, gap: 2 },
    agendaTitle: { color: colors.text, fontSize: 15, fontWeight: '600' },
    agendaCount: { color: colors.textMuted, fontSize: 12 },
    agendaClose: {
      width: 32,
      height: 32,
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: 6,
      backgroundColor: colors.surfaceMuted,
    },
    agendaCloseText: { color: colors.textMuted, fontSize: 18, lineHeight: 20 },
    tagRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      paddingHorizontal: 12,
      paddingVertical: 8,
    },
    filterChip: {
      minHeight: 30,
      flexDirection: 'row',
      alignItems: 'center',
      paddingHorizontal: 10,
      borderRadius: 6,
      borderWidth: 1,
      borderColor: colors.border,
      backgroundColor: colors.surface,
    },
    filterChipSelected: {
      borderColor: colors.accent,
      backgroundColor: colors.accentStrong,
    },
    filterChipText: { color: colors.textSecondary, fontSize: 12, fontWeight: '600' },
    filterChipTextSelected: { color: colors.accentText },
    agendaBody: { padding: 10, gap: 8 },
    agendaSection: { gap: 4 },
    agendaSectionDivider: {
      borderTopWidth: 1,
      borderTopColor: colors.border,
      paddingTop: 8,
    },
    agendaSectionTitle: {
      color: colors.textSecondary,
      fontSize: 12,
      fontWeight: '700',
      paddingHorizontal: 4,
      paddingVertical: 2,
    },
    emptyCard: {
      padding: 12,
      borderRadius: 8,
      backgroundColor: colors.surface,
    },
    emptyText: { color: colors.textMuted, fontSize: 13 },
    releaseRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      padding: 8,
      borderRadius: 8,
    },
    releaseArtwork: {
      width: 40,
      height: 40,
      borderRadius: 6,
      backgroundColor: colors.surfaceStrong,
    },
    releaseBody: { flex: 1, minWidth: 0, gap: 2 },
    releaseTitle: { color: colors.text, fontSize: 14, fontWeight: '600' },
    releaseLines: { color: colors.textMuted, fontSize: 11 },
    releaseMeta: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      flexWrap: 'wrap',
    },
    releaseSubtitle: { flexShrink: 1, fontSize: 11 },
    listStack: { gap: 12 },
    listDayCard: {
      backgroundColor: colors.surfaceMuted,
      borderRadius: 10,
      overflow: 'hidden',
    },
    listDayHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 8,
      paddingHorizontal: 12,
      paddingVertical: 10,
      backgroundColor: colors.surfaceStrong,
    },
    listDayHeaderToday: { backgroundColor: colors.accentStrong },
    listDayTitle: { color: colors.text, fontSize: 14, fontWeight: '600' },
    listDayBody: { padding: 10, gap: 6, backgroundColor: colors.surface },
    overlay: {
      flex: 1,
      justifyContent: compact ? 'flex-end' : 'center',
      alignItems: 'center',
      backgroundColor: colors.overlay,
    },
    backdrop: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0 },
    sheet: {
      width: compact ? '100%' : 440,
      maxHeight: compact ? '82%' : '78%',
      backgroundColor: colors.surface,
      borderWidth: 1,
      borderColor: colors.border,
      borderTopLeftRadius: 16,
      borderTopRightRadius: 16,
      borderBottomLeftRadius: compact ? 0 : 12,
      borderBottomRightRadius: compact ? 0 : 12,
      overflow: 'hidden',
    },
    menuSheet: {
      width: compact ? '100%' : 340,
      backgroundColor: colors.surface,
      borderWidth: 1,
      borderColor: colors.border,
      borderTopLeftRadius: 16,
      borderTopRightRadius: 16,
      borderBottomLeftRadius: compact ? 0 : 12,
      borderBottomRightRadius: compact ? 0 : 12,
      overflow: 'hidden',
    },
    sheetHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 8,
      paddingHorizontal: 16,
      paddingVertical: 12,
      borderBottomWidth: 1,
      borderBottomColor: colors.border,
    },
    sheetTitle: { color: colors.text, fontSize: 16, fontWeight: '700' },
    sheetClose: {
      width: 32,
      height: 32,
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: 8,
      backgroundColor: colors.surfaceStrong,
    },
    sheetCloseText: { color: colors.textSecondary, fontSize: 20, lineHeight: 22 },
    sheetBody: { flexGrow: 0 },
    sheetContent: { padding: 12, gap: 12 },
    filterSection: { gap: 6 },
    filterSectionTitle: {
      color: colors.textMuted,
      fontSize: 11,
      fontWeight: '700',
      letterSpacing: 0.8,
      textTransform: 'uppercase',
    },
    optionRow: {
      minHeight: 40,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 8,
      paddingHorizontal: 10,
      borderRadius: 8,
      backgroundColor: colors.surfaceStrong,
    },
    optionLabel: { flexShrink: 1, color: colors.textSecondary, fontSize: 14 },
    checkbox: {
      width: 22,
      height: 22,
      borderRadius: 4,
      borderWidth: 1,
      borderColor: colors.border,
      alignItems: 'center',
      justifyContent: 'center',
    },
    checkboxChecked: {
      backgroundColor: colors.accentStrong,
      borderColor: colors.accentStrong,
    },
    checkboxMark: { color: colors.accentText, fontSize: 13, fontWeight: '700' },
    clearAll: {
      minHeight: 42,
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: 8,
      borderWidth: 1,
      borderColor: colors.border,
    },
    clearAllText: { color: colors.textSecondary, fontSize: 13, fontWeight: '600' },
    menuBody: { padding: 8, gap: 4 },
    menuRow: {
      minHeight: 42,
      justifyContent: 'center',
      paddingHorizontal: 12,
      borderRadius: 8,
    },
    menuRowText: { color: colors.textSecondary, fontSize: 14 },
    menuGroup: { gap: 6, padding: 12 },
    menuGroupLabel: { color: colors.textMuted, fontSize: 12, fontWeight: '600' },
    menuGroupActions: { flexDirection: 'row', gap: 6 },
    menuChoice: {
      minHeight: 36,
      paddingHorizontal: 12,
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: 8,
      backgroundColor: colors.surfaceStrong,
    },
    menuChoiceSelected: { backgroundColor: colors.accentStrong },
    menuChoiceText: { color: colors.textSecondary, fontSize: 13, fontWeight: '600' },
    menuChoiceTextSelected: { color: colors.accentText },
  });
}
