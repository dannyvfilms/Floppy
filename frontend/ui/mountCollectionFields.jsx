import React, { useEffect, useMemo, useState } from 'react';
import { mountRoot } from '../settings/root';
import { Button } from './Button';
import {
  CollectionFieldManager,
  CollectionFieldValueInputs,
} from './CollectionCustomFields';

const palette = {
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  surface: 'var(--color-surface)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceMuted: 'var(--color-surface-muted)',
  border: 'var(--color-surface-border)',
  accent: 'var(--color-accent)',
  accentStrong: 'var(--color-accent-strong)',
  accentContrast: 'var(--color-accent-contrast)',
  danger: 'var(--color-error-text)',
  success: 'var(--color-status-clean)',
  warning: 'var(--color-warning-text)',
  overlay: 'rgba(0, 0, 0, 0.55)',
  focusStyle: {},
};

function csrfToken() {
  const input = document.querySelector('input[name=csrfmiddlewaretoken]');
  if (input) return input.value;
  return document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
}

function hydrate(schema, nextId) {
  return (schema || []).map((group) => ({
    clientId: `group-${nextId()}`,
    id: group.id,
    name: group.name,
    fields: (group.fields || []).map((field) => ({
      clientId: `field-${nextId()}`,
      id: field.id,
      label: field.label,
      fieldType: field.field_type || field.fieldType,
      options: field.options || [],
      optionsText: (field.options || []).join('\n'),
      mediaTypes: [...(field.media_types || field.mediaTypes || [])],
    })),
  }));
}

function serialize(groups, itemId, knownFieldIds) {
  return {
    item_id: itemId,
    known_field_ids: knownFieldIds,
    groups: (groups || []).map((group) => ({
      id: group.id,
      name: (group.name || '').trim(),
      fields: (group.fields || []).map((field) => ({
        id: field.id,
        label: (field.label || '').trim(),
        field_type: field.fieldType || field.field_type,
        media_types: [...(field.mediaTypes || field.media_types || [])],
        options: (field.fieldType || field.field_type) === 'select'
          ? String(field.optionsText ?? (field.options || []).join('\n'))
            .split('\n').map((option) => option.trim()).filter(Boolean)
          : [],
      })),
    })),
  };
}

function visibleGroups(schema, mediaType) {
  return (schema || [])
    .map((group) => ({
      ...group,
      fields: (group.fields || []).filter(
        (field) => (field.media_types || field.mediaTypes || []).includes(mediaType),
      ),
    }))
    .filter((group) => group.fields.length);
}

function useHiddenValues(host, formId, groups, values) {
  useEffect(() => {
    const form = (formId && document.getElementById(formId)) || host.closest('form');
    if (!form) return;
    form.querySelectorAll('input[data-collection-field-hidden]').forEach((input) => input.remove());
    groups.forEach((group) => (group.fields || []).forEach((field) => {
      const key = String(field.id);
      if (!(key in values)) return;
      const value = values[key];
      if (value === '' || value === null || value === undefined || value === false) return;
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = `custom_field_${field.id}`;
      input.value = value === true ? 'on' : String(value);
      input.setAttribute('data-collection-field-hidden', '');
      if (formId) input.setAttribute('form', formId);
      form.appendChild(input);
    }));
  }, [host, formId, groups, values]);
}

function ValuesAdapter({ host, props }) {
  const [values, setValues] = useState(props.values || {});
  const groups = useMemo(
    () => visibleGroups(props.groups || [], props.itemMediaType),
    [props.groups, props.itemMediaType],
  );
  useHiddenValues(host, props.formId, groups, values);

  return <CollectionFieldValueInputs
    groups={groups}
    values={values}
    labels={props.labels}
    palette={palette}
    canEdit
    onChange={(key, value) => setValues((current) => ({ ...current, [key]: value }))} />;
}

function ManagerAdapter({ host, props }) {
  const [schema, setSchema] = useState(props.schema || []);
  const [draft, setDraft] = useState(() => {
    let counter = 0;
    return hydrate(props.schema || [], () => ++counter);
  });
  const [baseline, setBaseline] = useState(draft);
  const [managing, setManaging] = useState(!!props.manageOpen);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [values, setValues] = useState(props.values || {});
  const knownFieldIds = useMemo(
    () => (props.schema || []).flatMap((group) => (group.fields || [])
      .map((field) => field.id).filter((id) => id != null)),
    [props.schema],
  );
  const groups = useMemo(
    () => visibleGroups(schema, props.itemMediaType),
    [schema, props.itemMediaType],
  );
  useHiddenValues(host, props.formId, groups, values);

  function validate(groups) {
    for (const group of groups) {
      if (!String(group.name || '').trim()) return 'Every group needs a name.';
      for (const field of group.fields || []) {
        if (!String(field.label || '').trim()) return 'Every field needs a label.';
        if (!(field.mediaTypes || []).length) {
          return `"${field.label}" needs at least one media type.`;
        }
      }
    }
    return '';
  }

  async function save() {
    if (saving) return;
    const localError = validate(draft);
    if (localError) {
      setError(localError);
      return;
    }
    setSaving(true);
    setError('');
    try {
      const response = await window.fetch(props.saveUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken(),
        },
        body: JSON.stringify(serialize(draft, props.itemId, knownFieldIds)),
      });
      const payload = await response.json();
      if (!response.ok || !payload.success) {
        throw new Error((payload && payload.error) || 'Could not save custom fields.');
      }
      setSchema(payload.groups || []);
      let counter = 1000;
      const next = hydrate(payload.groups || [], () => ++counter);
      setDraft(next);
      setBaseline(next);
      setManaging(false);
    } catch (saveError) {
      setError(saveError.message || 'Could not save custom fields.');
    } finally {
      setSaving(false);
    }
  }

  function toggleManaging() {
    let counter = draft.length * 100;
    const next = hydrate(schema, () => ++counter);
    setDraft(next);
    setBaseline(next);
    setError('');
    setManaging((current) => !current);
  }

  const dirty = JSON.stringify(serialize(draft, props.itemId, knownFieldIds))
    !== JSON.stringify(serialize(baseline, props.itemId, knownFieldIds));

  return <>
    <CollectionFieldValueInputs
      groups={groups}
      values={values}
      labels={props.labels}
      palette={palette}
      canEdit
      onChange={(key, value) => setValues((current) => ({ ...current, [key]: value }))} />
    {managing ? <CollectionFieldManager
      groups={draft}
      fieldTypes={props.fieldTypes || []}
      mediaTypes={props.mediaTypes || []}
      labels={props.labels}
      palette={palette}
      canManage
      dirty={dirty}
      saving={saving}
      error={error}
      onChange={setDraft}
      onSave={save}
      onReset={() => {
        let counter = draft.length * 100;
        setDraft(hydrate(schema, () => ++counter));
        setError('');
      }} /> : null}
    <Button
      label={managing ? 'Done managing fields' : 'Manage custom fields'}
      tone="surface"
      palette={palette}
      onPress={toggleManaging} />
  </>;
}

export function mountCollectionFields(host, props) {
  return mountRoot(host, <ManagerAdapter host={host} props={props} />);
}

export function mountCollectionFieldValues(host, props) {
  return mountRoot(host, <ValuesAdapter host={host} props={props} />);
}
