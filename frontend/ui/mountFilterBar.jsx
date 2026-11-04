import React, { useEffect, useState } from 'react';
import { mountRoot } from '../settings/root';
import { FilterBar } from './FilterBar';

const rangeFields = {
  rating: { from: 'rating_min', to: 'rating_max' },
  releaseDate: {
    from: 'release_date_from',
    to: 'release_date_to',
    within: 'release_date_within',
    unit: 'release_date_within_unit',
  },
  dateAdded: {
    from: 'date_added_from',
    to: 'date_added_to',
    within: 'date_added_within',
    unit: 'date_added_within_unit',
  },
  completedDate: {
    from: 'completed_date_from',
    to: 'completed_date_to',
    within: 'completed_date_within',
    unit: 'completed_date_within_unit',
  },
};

function rangeState(data, fields) {
  if (!fields) {
    return { from: '', to: '', within: '', unit: 'days' };
  }
  return {
    from: data[fields.from] || '',
    to: data[fields.to] || '',
    within: fields.within ? data[fields.within] || '' : '',
    unit: fields.unit ? data[fields.unit] || 'days' : 'days',
  };
}

function readFilters(host, props) {
  const data = window.Alpine?.$data(host);
  if (!data) {
    return props.filters || {};
  }
  const ranges = {};
  for (const range of props.options?.ranges || []) {
    ranges[range.key] = rangeState(data, rangeFields[range.key]);
  }
  return {
    mediaTypes: [...(data.selectedTypes || [])],
    statuses: [...(data.statuses || [])],
    sort: data.sort || '',
    direction: data.direction || 'asc',
    view: data.layout || 'grid',
    ranges,
  };
}

function writeIntent(data, intent, props) {
  if (intent.type === 'toggle') {
    if (intent.key === 'mediaTypes') data.toggleMediaType?.(intent.value);
    if (intent.key === 'statuses') data.toggleStatus?.(intent.value);
    return;
  }
  if (intent.type === 'set') {
    if (intent.key === 'statuses') {
      data.statuses = intent.value;
    } else if (intent.key === 'view') {
      data.layout = intent.value;
    } else {
      data[intent.key] = intent.value;
    }
    return;
  }
  if (intent.type === 'range') {
    const fields = rangeFields[intent.key];
    if (!fields) {
      return;
    }
    data[fields.from] = intent.value?.from || '';
    data[fields.to] = intent.value?.to || '';
    if (fields.within) {
      data[fields.within] = intent.value?.within || '';
    }
    if (fields.unit) {
      data[fields.unit] = intent.value?.unit || 'days';
    }
    return;
  }
  if (intent.type === 'clear') {
    data.clearFilters?.();
    data.statuses = [];
    return;
  }
  if (intent.type === 'savedView') {
    const url = props.savedViewUrls?.[intent.value];
    if (url) {
      window.location.assign(url);
    }
  }
}

function Adapter({ host, props }) {
  const [filters, setFilters] = useState(() => readFilters(host, props));

  useEffect(() => {
    const Alpine = window.Alpine;
    if (!Alpine) {
      return undefined;
    }
    const runner = Alpine.effect(() => setFilters(readFilters(host, props)));
    return () => Alpine.release(runner);
  }, [host, props]);

  function commit(intent) {
    if (intent.type === 'savedView') {
      writeIntent(null, intent, props);
      return;
    }
    const data = window.Alpine?.$data(host);
    if (!data) {
      return;
    }
    writeIntent(data, intent, props);
    if (intent.type === 'set' && intent.key === 'view' && typeof data.layoutHref === 'function') {
      window.location.assign(data.layoutHref(intent.value));
      return;
    }
    // Alpine owns the hidden filter form; wait for its flush before htmx reads it.
    window.setTimeout(() => {
      window.applyFilterChange?.(props.endpoint, props.target, props.formId || 'filter-form');
    }, 0);
  }

  return <FilterBar filters={filters} options={props.options} labels={props.labels}
    palette={props.palette} busy={props.busy} disabled={props.disabled}
    resultCount={props.resultCount} onChange={commit} />;
}

export function mountFilterBar(host, props) {
  return mountRoot(host, <Adapter host={host} props={props} />);
}
