export const ALL_LISTS = '';

function asString(value) {
  return value == null ? '' : String(value);
}

export function normalizeListsModel(payload) {
  const source = payload || {};
  const lists = (source.lists || []).map(list => ({
    id: asString(list.id),
    name: list.name || '',
    hasItem: Boolean(list.hasItem),
    tags: Array.isArray(list.tags) ? list.tags.filter(tag => typeof tag === 'string') : [],
  }));
  return {
    itemId: source.itemId ?? null,
    title: source.title || '',
    lists,
    tags: Array.isArray(source.tags) ? source.tags.filter(tag => typeof tag === 'string') : [],
    selectedTag: source.selectedTag || '',
    toggleUrl: source.toggleUrl || '',
    csrfToken: source.csrfToken || '',
  };
}

export function listsMembership(model) {
  return Object.fromEntries((model?.lists || []).map(list => [list.id, Boolean(list.hasItem)]));
}

export function listsCount(model, membership) {
  return (model?.lists || []).filter(list => membership?.[list.id]).length;
}

export function listsCountLabel(labels, count) {
  const template = count === 1 ? labels?.countOne : labels?.countMany;
  return asString(template || '%s').replace('%s', String(count));
}

export function visibleLists(model, tag) {
  const lists = model?.lists || [];
  if (!tag) return lists;
  const wanted = tag.toLowerCase();
  return lists.filter(list => list.tags.some(entry => entry.toLowerCase() === wanted));
}

export function applyListToggle(membership, listId, hasItem) {
  return { ...membership, [asString(listId)]: Boolean(hasItem) };
}

function normalizeField(field) {
  return {
    name: field.name,
    label: field.label || field.name,
    type: field.type || 'text',
    value: field.value ?? '',
    required: Boolean(field.required),
    options: (field.options || []).map(option => ({
      value: asString(option.value),
      label: option.label == null ? asString(option.value) : String(option.label),
    })),
    help: field.help || '',
    min: field.min ?? null,
    max: field.max ?? null,
    step: field.step ?? null,
    placeholder: field.placeholder || '',
  };
}

export function normalizeTrackForm(payload) {
  const source = payload || {};
  const fields = (source.fields || []).map(normalizeField);
  if (source.notes && source.notes.value != null) {
    fields.push(normalizeField({
      name: 'notes',
      label: source.notes.label || 'Notes',
      type: 'textarea',
      value: source.notes.value,
      help: source.notes.help || '',
    }));
  }
  return {
    mediaType: source.mediaType || '',
    variant: source.variant || '',
    title: source.title || '',
    subtitle: source.titleSubtitle || source.subtitle || '',
    formId: source.formId || '',
    instanceId: source.instanceId ?? null,
    isNew: source.isNew,
    action: source.action || '',
    deleteAction: source.deleteAction || '',
    csrfToken: source.csrfToken || '',
    fields,
    hidden: source.hidden || {},
    submitLabel: source.submitLabel || 'Save',
    secondaryActions: (source.secondaryActions || []).map(action => ({
      key: asString(action.key),
      label: asString(action.label),
      tone: action.tone || 'surface',
      url: action.url || '',
      body: action.body || {},
    })),
    target: source.target || '',
    swap: source.swap || 'none',
    legacyIds: (source.legacyIds || []).map(asString).filter(Boolean),
    deleteLabel: source.deleteLabel || 'Delete',
    trackTime: Boolean(source.trackTime),
    labels: source.labels || {},
    repeatIdentity: source.repeatIdentity || null,
  };
}

export function initialTrackValues(model) {
  return Object.fromEntries((model?.fields || []).map(field => [field.name, field.value ?? '']));
}

export function validateTrackValues(model, values, labels = {}) {
  const errors = {};
  for (const field of model?.fields || []) {
    const value = values?.[field.name];
    const empty = value === '' || value == null;
    if (field.required && empty) {
      errors[field.name] = asString(labels.required || '%s is required.').replace('%s', field.label);
      continue;
    }
    if (!empty && field.type === 'number') {
      const number = Number(value);
      if (Number.isNaN(number)) {
        errors[field.name] = asString(labels.invalidNumber || 'Enter a number.');
      } else if (field.min != null && number < Number(field.min)) {
        errors[field.name] = asString(labels.minimum || 'Must be at least %s.').replace('%s', String(field.min));
      } else if (field.max != null && number > Number(field.max)) {
        errors[field.name] = asString(labels.maximum || 'Must be at most %s.').replace('%s', String(field.max));
      }
    }
  }
  if (values?.start_date && values?.end_date && values.start_date > values.end_date) {
    errors.end_date = labels.dateOrder || 'End date must be on or after the start date.';
  }
  return errors;
}

export function normalizeBulkEpisodeForm(payload) {
  const source = payload || {};
  return {
    formId: source.formId || '',
    action: source.action || '',
    csrfToken: source.csrfToken || '',
    trackTime: Boolean(source.trackTime),
    hidden: source.hidden || {},
    values: source.values || {},
    domain: source.domain || {},
    seasonOptions: source.seasonOptions || [],
    writeModeOptions: source.writeModeOptions || [],
    distributionModeOptions: source.distributionModeOptions || [],
    submitLabel: source.submitLabel || 'Save plays',
    notice: source.notice || '',
    errors: source.errors || {},
    labels: source.labels || {},
  };
}
