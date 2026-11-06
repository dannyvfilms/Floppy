import React, { useEffect, useRef, useState } from 'react';
import { mountRoot } from '../settings/root';
import { ImportPreferencesCard } from './ImportSettings';
import { readThemePalette, savePreferenceValues } from './transport.web';

const modeOptions = [
  { value: 'history', label: 'History' },
  { value: 'watchlist', label: 'Watchlist' },
  { value: 'update_collection', label: 'Collection' },
];
const overrideOptions = [
  { value: 'new', label: 'New Items Only' },
  { value: 'overwrite', label: 'Overwrite Existing' },
];
const frequencyOptions = [
  { value: 'once', label: 'One Time Import' },
  { value: 'daily', label: 'Every Day' },
  { value: '2days', label: 'Every 2 Days' },
];

function translatedOptions(options, t) {
  return options.map(option => ({ ...option, label: t(option.label) }));
}

function preferencesModel(initial, t) {
  return {
    title: t('Import preferences'),
    profile: initial.profile,
    editable: initial.editable,
    fixed: initial.fixed,
    fixedFrequency: initial.fixedFrequency,
    fixedFrequencyHelp: initial.fixedFrequencyHelp,
    values: initial.values || {},
    statuses: initial.statuses || [],
    tags: initial.tags || [],
    tagNames: initial.tagNames || [],
    modeOptions: translatedOptions(modeOptions, t),
    overrideOptions: translatedOptions(overrideOptions, t),
    frequencyOptions: translatedOptions(frequencyOptions, t),
    labels: initial.labels || {},
  };
}

function ImportPreferencesHost({ host, initial }) {
  const t = text => initial.labels?.[text] ?? text;
  const saveUrl = initial.saveUrl;
  const csrf = initial.csrf;
  const parent = host.closest('[x-data]');
  const initialValues = useRef(initial.values || {});
  const [values, setValues] = useState(initialValues.current);

  function broadcast(next) {
    if (parent) parent.importPreferences = next;
    host.dispatchEvent(new CustomEvent('import-preferences-changed', { bubbles: true, detail: next }));
  }

  useEffect(() => {
    // Publish the saved values once so sibling file-import forms start in sync.
    broadcast(values);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <ImportPreferencesCard
    model={preferencesModel(initial, t)}
    palette={readThemePalette()}
    onValuesChange={next => { setValues(next); broadcast(next); }}
    onSave={next => {
      setValues(next);
      broadcast(next);
      return savePreferenceValues({ url: saveUrl, csrf, values: next });
    }}
  />;
}

export function mountImportPreferences(host, initial) {
  return mountRoot(host, <ImportPreferencesHost host={host} initial={initial} />);
}
