// Filter state behind the shared filter menu and hidden filter form
// (templates/app/components/filter_menu.html and filter_form.html).
//
// A page spreads it into its own x-data:
//   x-data="{ ...libraryFilterState(rules, filterData, mediaTypes), sort: ..., ... }"
// `rules` is the server's normalized filter rules (lists.smart_rules keys:
// status, tag, tag_mode, rating, genre, year, media_types, ...). `filterData`
// is the menu's option payload; only its show_* flags are read here.
// `mediaTypes` feeds the menu's Media Types pane (filter_show_media_types):
// `available` is [{value, label}], and `granular` lists types (season,
// episode) that "all types" leaves out.
// eslint-disable-next-line no-unused-vars
function libraryFilterState(rules = {}, filterData = {}, mediaTypes = {}) {
  const value = (key, fallback = '') => rules[key] || fallback;
  const availableMediaTypes = mediaTypes.available || [];
  const granularMediaTypes = mediaTypes.granular || [];
  const broadMediaTypes = availableMediaTypes
    .map((type) => type.value)
    .filter((type) => !granularMediaTypes.includes(type));
  return {
    statuses: [...(rules.status || [])],
    rating: value('rating', 'all'),
    progress: value('progress', 'all'),
    rating_min: value('rating_min'),
    rating_max: value('rating_max'),
    collection: value('collection', 'all'),
    group_by: value('group_by', 'item'),
    genre: value('genre'),
    implied_genre: value('implied_genre'),
    year: value('year'),
    release: value('release', 'all'),
    release_date_from: value('release_date_from'),
    release_date_to: value('release_date_to'),
    release_date_within: value('release_date_within'),
    release_date_within_unit: value('release_date_within_unit', 'days'),
    date_added_from: value('date_added_from'),
    date_added_to: value('date_added_to'),
    date_added_within: value('date_added_within'),
    date_added_within_unit: value('date_added_within_unit', 'days'),
    completed_date_from: value('completed_date_from'),
    completed_date_to: value('completed_date_to'),
    completed_date_within: value('completed_date_within'),
    completed_date_within_unit: value('completed_date_within_unit', 'days'),
    author: value('author'),
    source: value('source'),
    media_status: value('media_status'),
    department: value('department'),
    language: value('language'),
    country: value('country'),
    platform: value('platform'),
    // Pages with a multi-select platform pane (the media list) use these.
    selectedPlatforms: [...(rules.platforms || [])],
    platformMode: value('platform_mode', 'or'),
    origin: value('origin'),
    format: value('format'),
    provider: value('provider'),
    selectedTags: [...(rules.tag || [])],
    tagMode: value('tag_mode', 'or'),
    selectedLists: [...(rules.list || [])],
    availableMediaTypes,
    granularMediaTypes,
    // No saved selection means every broad type.
    selectedTypes: (rules.media_types || []).length ? [...rules.media_types] : broadMediaTypes,
    showLanguages: Boolean(filterData.show_languages),
    showCountries: Boolean(filterData.show_countries),
    showPlatforms: Boolean(filterData.show_platforms),
    showOrigins: Boolean(filterData.show_origins),
    showFormats: Boolean(filterData.show_formats),
    showProviders: Boolean(filterData.show_providers),
    showAuthors: Boolean(filterData.show_authors),
    showProgress: Boolean(filterData.show_progress),
    ratingLabels: {
      all: gettext('All'),
      rated: gettext('Rated'),
      not_rated: gettext('Not Rated'),
    },
    collectionLabels: {
      all: gettext('All'),
      collected: gettext('Collected'),
      not_collected: gettext('Not Collected'),
    },
    progressLabels: {
      all: gettext('Any'),
      not_caught_up: gettext('Not Caught Up'),
      caught_up: gettext('Caught Up'),
    },
    releaseLabels: {
      all: gettext('Any'),
      released: gettext('Released'),
      not_released: gettext('Not Released'),
    },
    groupByLabels: {
      item: gettext('Item'),
      series: gettext('Collection/Series'),
      franchise: gettext('Franchise'),
    },
    isStatusSelected(status) {
      return this.statuses.includes(status);
    },
    toggleStatus(status) {
      this.statuses = this.statuses.includes(status)
        ? this.statuses.filter((s) => s !== status)
        : [...this.statuses, status];
    },
    isTagSelected(tag) {
      return this.selectedTags.includes(tag);
    },
    toggleTag(tag) {
      this.selectedTags = this.selectedTags.includes(tag)
        ? this.selectedTags.filter((t) => t !== tag)
        : [...this.selectedTags, tag];
    },
    isPlatformSelected(platform) {
      return this.selectedPlatforms.includes(platform);
    },
    togglePlatform(platform) {
      this.selectedPlatforms = this.selectedPlatforms.includes(platform)
        ? this.selectedPlatforms.filter((p) => p !== platform)
        : [...this.selectedPlatforms, platform];
    },
    cyclePlatformMode() {
      this.platformMode = this.platformMode === 'and' ? 'or' : (this.platformMode === 'or' ? 'not' : 'and');
    },
    cycleTagMode() {
      this.tagMode = this.tagMode === 'and' ? 'or' : (this.tagMode === 'or' ? 'not' : 'and');
    },
    broadMediaTypes() {
      return broadMediaTypes;
    },
    hasGranularTypeSelected() {
      return this.selectedTypes.some((type) => this.granularMediaTypes.includes(type));
    },
    allTypesSelected() {
      return broadMediaTypes.length > 0 && broadMediaTypes.every((type) => this.selectedTypes.includes(type));
    },
    isTypeSelected(mediaType) {
      return this.selectedTypes.includes(mediaType);
    },
    toggleMediaType(mediaType) {
      this.selectedTypes = this.selectedTypes.includes(mediaType)
        ? this.selectedTypes.filter((type) => type !== mediaType)
        : [...this.selectedTypes, mediaType];
    },
    toggleAllTypes() {
      const granular = this.selectedTypes.filter((type) => this.granularMediaTypes.includes(type));
      this.selectedTypes = this.allTypesSelected() ? granular : [...broadMediaTypes, ...granular];
    },
    // The Media Types pane's row text; a page may mark types (the calendar).
    typeLabel(type) {
      return type.label;
    },
    typesFiltered() {
      return !this.allTypesSelected() || this.hasGranularTypeSelected();
    },
    dropdownLabel() {
      if (!this.typesFiltered()) return gettext('All Types');
      if (this.selectedTypes.length === 0) return gettext('No Types');
      if (this.selectedTypes.length === 1) {
        const match = this.availableMediaTypes.find((type) => type.value === this.selectedTypes[0]);
        return match ? match.label : gettext('1 Type');
      }
      return interpolate(gettext('%(count)s Types'), { count: this.selectedTypes.length }, true);
    },
    // All broad types submit as no type filter.
    selectedTypesForSubmit() {
      return this.typesFiltered() ? this.selectedTypes : [];
    },
    formatRangeLabel(minValue, maxValue) {
      if (minValue && maxValue) return `${minValue}-${maxValue}`;
      if (minValue) return `>=${minValue}`;
      if (maxValue) return `<=${maxValue}`;
      return '';
    },
    formatDateRangeLabel(prefix, fromValue, toValue) {
      if (!fromValue && !toValue) return '';
      const fromYear = /^(\d{4})-01-01$/.exec(fromValue || '');
      const toYear = /^(\d{4})-12-31$/.exec(toValue || '');
      if (fromYear && toYear) return `${fromYear[1]}-${toYear[1]}`;
      const labelPrefix = prefix ? `${prefix} ` : '';
      if (fromValue && toValue) return `${labelPrefix}${fromValue}-${toValue}`;
      if (fromValue) return `${labelPrefix}>=${fromValue}`;
      return `${labelPrefix}<=${toValue}`;
    },
    // A completed-date range spanning exactly one calendar year reads as that year.
    completedYearLabel() {
      const from = this.completed_date_from;
      const to = this.completed_date_to;
      const year = (from || '').slice(0, 4);
      if (from && to && from === `${year}-01-01` && to === `${year}-12-31`) return year;
      return gettext('Pick a year…');
    },
    // Labels for the active attribute filters, in menu order. A page adds its
    // own (linked lists) through extraFilterLabels().
    filterLabel() {
      const upperCode = (code) => (code.length <= 3 ? code.toUpperCase() : code);
      const labels = [...(this.extraFilterLabels ? this.extraFilterLabels() : [])];
      if (this.availableMediaTypes.length && this.typesFiltered()) labels.unshift(this.dropdownLabel());
      if (this.rating && this.rating !== 'all') labels.push(this.ratingLabels[this.rating]);
      labels.push(this.formatRangeLabel(this.rating_min, this.rating_max));
      if (this.collection && this.collection !== 'all') labels.push(this.collectionLabels[this.collection]);
      if (this.group_by && this.group_by !== 'item') labels.push(this.groupByLabels[this.group_by]);
      if (this.progress && this.progress !== 'all') labels.push(this.progressLabels[this.progress]);
      labels.push(this.genre);
      if (this.implied_genre) labels.push(gettext('Implied: ') + this.implied_genre);
      if (this.year) labels.push(this.year === 'unknown' ? gettext('Unknown Year') : this.year);
      if (this.release && this.release !== 'all') labels.push(this.releaseLabels[this.release]);
      labels.push(
        relativeWindowLabel(this.release_date_within, this.release_date_within_unit)
          || this.formatDateRangeLabel(gettext('Release'), this.release_date_from, this.release_date_to),
        relativeWindowLabel(this.date_added_within, this.date_added_within_unit)
          || this.formatDateRangeLabel(gettext('Added'), this.date_added_from, this.date_added_to),
        relativeWindowLabel(this.completed_date_within, this.completed_date_within_unit)
          || this.formatDateRangeLabel(gettext('Completed'), this.completed_date_from, this.completed_date_to),
        this.author,
        this.source.toUpperCase(),
        this.media_status,
        this.department,
      );
      if (this.showLanguages && this.language) labels.push(upperCode(this.language));
      if (this.showCountries && this.country) labels.push(upperCode(this.country));
      if (this.showPlatforms && this.selectedPlatforms.length) {
        const prefix = this.platformMode === 'not' ? '-' : '+';
        labels.push(prefix + this.selectedPlatforms.join(this.platformMode === 'and' ? ' & ' : ', '));
      } else if (this.showPlatforms) {
        labels.push(this.platform);
      }
      if (this.showOrigins && this.origin) labels.push(upperCode(this.origin));
      if (this.showFormats && this.format) {
        labels.push(this.format === 'ebook' ? 'eBook' : this.format.charAt(0).toUpperCase() + this.format.slice(1));
      }
      if (this.showProviders) labels.push(this.provider);
      if (this.selectedTags.length) {
        const prefix = this.tagMode === 'not' ? '-' : '+';
        labels.push(prefix + this.selectedTags.join(this.tagMode === 'and' ? ' & ' : ', '));
      }
      const active = labels.filter(Boolean);
      if (active.length === 0) return gettext('All');
      return active.length === 1 ? active[0] : `${active[0]} +${active.length - 1}`;
    },
    clearFilters() {
      Object.assign(this, {
        rating: 'all',
        rating_min: '',
        rating_max: '',
        collection: 'all',
        group_by: 'item',
        progress: 'all',
        genre: '',
        implied_genre: '',
        year: '',
        release: 'all',
        release_date_from: '',
        release_date_to: '',
        release_date_within: '',
        date_added_from: '',
        date_added_to: '',
        date_added_within: '',
        completed_date_from: '',
        completed_date_to: '',
        completed_date_within: '',
        author: '',
        source: '',
        media_status: '',
        department: '',
        language: '',
        country: '',
        platform: '',
        selectedPlatforms: [],
        platformMode: 'or',
        origin: '',
        format: '',
        provider: '',
        selectedTags: [],
        tagMode: 'or',
        selectedLists: [],
      });
    },
  };
}
