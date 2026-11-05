import './settings-card.css';
import '../ui/controls.css';
import '../ui/alphabet.css';
import '../ui/media-card.css';
import '../ui/global-search.css';
import '../ui/sidebar.css';
import '../ui/modal-forms.css';
import '../providers/provider-page.css';

// One small loader on every page; React/RNW are fetched only when a card appears.
const roots = new Map();
const renderers = {};
const selector = '[data-users-management-root], [data-history-feed-root], [data-modal-host-root], [data-spinner-root], [data-badge-root], [data-button-root], [data-progress-changer-root], [data-progress-breakdown-root], [data-date-time-picker-root], [data-filter-chips-root], [data-sidebar-root], [data-global-search-root], [data-search-results-root], [data-parent-picker-root], [data-media-card-root], [data-bulk-actions-root], [data-bulk-toolbar-root], [data-rating-stars-root], [data-rating-chip-root], [data-alphabet-root], [data-settings-card-root], [data-provider-root], [data-provider-credentials-root], [data-setup-guide-root], [data-settings-form-root], [data-provider-directory-root], [data-tooltip-root], [data-import-preferences-root], [data-link-chip-root], [data-account-connection-root], [data-account-import-action-root], [data-file-import-root], [data-backup-status-root], [data-release-calendar-root], [data-calendar-links-root], [data-detail-composition-root]';
const hostsWithin = (element) => [
  ...(element.matches?.(selector) ? [element] : []),
  ...element.querySelectorAll?.(selector) || [],
].filter(host => (!host.matches('[data-spinner-root], [data-badge-root], [data-button-root], [data-progress-changer-root]') || !host.parentElement.closest(selector)) &&
  (host.matches('[data-provider-root]') || !host.closest('[data-provider-root]')) &&
  (host.matches('[data-import-preferences-root]') || !host.closest('[data-import-preferences-root]')) &&
  (host.matches('[data-account-connection-root]') || !host.closest('[data-account-connection-root]')) &&
  (host.matches('[data-search-results-root]') || !host.closest('[data-search-results-root]')) &&
  (host.matches('[data-parent-picker-root]') || !host.closest('[data-parent-picker-root]')) &&
  (host.matches('[data-history-feed-root]') || !host.closest('[data-history-feed-root]')));

async function mountWithin(element) {
  const hosts = hostsWithin(element);
  if (!hosts.length) return;
  // Islands mount side by side so one slow chunk never holds up the others.
  await Promise.all(hosts.map(async (host) => {
    const kind = host.matches('[data-users-management-root]') ? 'usersManagement' : host.matches('[data-history-feed-root]') ? 'historyFeed' : host.matches('[data-detail-composition-root]') ? 'detailComposition' : host.matches('[data-date-time-picker-root]') ? 'dateTimePicker' : host.matches('[data-release-calendar-root]') ? 'releaseCalendar' : host.matches('[data-calendar-links-root]') ? 'calendarLinks' : host.matches('[data-modal-host-root]') ? 'modalHost' : host.matches('[data-spinner-root]') ? 'spinner' : host.matches('[data-badge-root]') ? 'badge' : host.matches('[data-button-root]') ? 'button' : host.matches('[data-progress-changer-root]') ? 'progressChanger' : host.matches('[data-progress-breakdown-root]') ? 'progressBreakdown' : host.matches('[data-filter-chips-root]') ? 'filterChips' : host.matches('[data-sidebar-root]') ? 'sidebar' : host.matches('[data-global-search-root]') ? 'globalSearch' : host.matches('[data-search-results-root]') ? 'searchResults' : host.matches('[data-parent-picker-root]') ? 'parentPicker' : host.matches('[data-media-card-root]') ? 'mediaCard' : host.matches('[data-bulk-toolbar-root]') ? 'bulkToolbar' : host.matches('[data-bulk-actions-root]') ? 'bulkActions' : host.matches('[data-rating-stars-root]') ? 'ratingStars' : host.matches('[data-rating-chip-root]') ? 'ratingChip' : host.matches('[data-alphabet-root]') ? 'alphabet' : host.matches('[data-backup-status-root]') ? 'backupStatus' : host.matches('[data-file-import-root]') ? 'fileImport' : host.matches('[data-account-import-action-root]') ? 'accountImportAction' : host.matches('[data-account-connection-root]') ? 'accountConnection' : host.matches('[data-link-chip-root]') ? 'linkChip' : host.matches('[data-import-preferences-root]') ? 'importPreferences' : host.matches('[data-tooltip-root]') ? 'tooltip' : host.matches('[data-provider-directory-root]') ? 'directory' : host.matches('[data-settings-form-root]') ? 'settingsForm' : host.matches('[data-setup-guide-root]') ? 'guide' : host.matches('[data-provider-credentials-root]') ? 'credentials' : host.matches('[data-provider-root]') ? 'provider' : 'card';
    try {
      renderers[kind] ??= (kind === 'usersManagement' ? import('./mount.jsx') : kind === 'historyFeed' ? import('../ui/mountHistoryFeed.jsx') : kind === 'detailComposition' ? import('../ui/mountDetailComposition.jsx') : kind === 'dateTimePicker' ? import('../ui/mountDateTimePicker.jsx') : kind === 'releaseCalendar' ? import('../ui/mountReleaseCalendar.jsx') : kind === 'calendarLinks' ? import('../ui/mountCalendarLinks.jsx') : kind === 'modalHost' ? import('../ui/mountModalHost.jsx') : kind === 'spinner' ? import('../ui/mountSpinner.jsx') : kind === 'badge' ? import('../ui/mountBadge.jsx') : kind === 'button' ? import('../ui/mountButton.jsx') : kind === 'progressChanger' ? import('../ui/mountProgressChanger.jsx') : kind === 'progressBreakdown' ? import('../ui/mountProgressBreakdown.jsx') : kind === 'filterChips' ? import('../ui/mountFilterChips.jsx') : kind === 'sidebar' ? import('../ui/mountSidebar.jsx') : kind === 'globalSearch' ? import('../ui/mountGlobalSearch.jsx') : kind === 'searchResults' ? import('../ui/mountSearchResults.jsx') : kind === 'parentPicker' ? import('../ui/mountParentPicker.jsx') : kind === 'mediaCard' ? import('../ui/mountMediaCard.jsx') : kind === 'bulkToolbar' ? import('../ui/mountBulkToolbar.jsx') : kind === 'bulkActions' ? import('../ui/mountBulkActions.jsx') : kind === 'ratingStars' ? import('../ui/mountRatingStars.jsx') : kind === 'ratingChip' ? import('../ui/mountRatingChip.jsx') : kind === 'alphabet' ? import('../ui/mountAlphabet.jsx') : kind === 'backupStatus' ? import('./BackupStatus.jsx') : kind === 'fileImport' ? import('../providers/FileImport.jsx') : (kind === 'accountConnection' || kind === 'accountImportAction') ? import('../providers/AccountConnection.jsx') : kind === 'importPreferences' ? import('../providers/ImportPreferences.jsx') : kind === 'directory' ? import('../providers/Directory.jsx') : kind === 'settingsForm' ? import('../providers/SettingsForm.jsx') : kind === 'guide' ? import('../providers/SetupGuide.jsx') : kind === 'credentials' ? import('../providers/Credentials.jsx') : kind === 'provider' ? import('../providers/mount.jsx') : import('./mount.jsx'))
        .catch(error => { delete renderers[kind]; throw error; });
      const renderer = await renderers[kind];
      if (!host.isConnected || roots.has(host)) return;
      const script = document.getElementById(host.dataset.propsId);
      if (!script || !host.parentElement.contains(script)) return;
      const props = JSON.parse(script.textContent);
      roots.set(host, (kind === 'usersManagement' ? renderer.mountUsersManagement : kind === 'historyFeed' ? renderer.mountHistoryFeed : kind === 'detailComposition' ? renderer.mountDetailComposition : kind === 'dateTimePicker' ? renderer.mountDateTimePicker : kind === 'releaseCalendar' ? renderer.mountReleaseCalendar : kind === 'calendarLinks' ? renderer.mountCalendarLinks : kind === 'modalHost' ? renderer.mountModalHost : kind === 'spinner' ? renderer.mountSpinner : kind === 'badge' ? renderer.mountBadge : kind === 'button' ? renderer.mountButton : kind === 'progressChanger' ? renderer.mountProgressChanger : kind === 'progressBreakdown' ? renderer.mountProgressBreakdown : kind === 'filterChips' ? renderer.mountFilterChips : kind === 'sidebar' ? renderer.mountSidebar : kind === 'globalSearch' ? renderer.mountGlobalSearch : kind === 'searchResults' ? renderer.mountSearchResults : kind === 'parentPicker' ? renderer.mountParentPicker : kind === 'mediaCard' ? renderer.mountMediaCard : kind === 'bulkToolbar' ? renderer.mountBulkToolbar : kind === 'bulkActions' ? renderer.mountBulkActions : kind === 'ratingStars' ? renderer.mountRatingStars : kind === 'ratingChip' ? renderer.mountRatingChip : kind === 'alphabet' ? renderer.mountAlphabet : kind === 'backupStatus' ? renderer.mountBackupStatus : kind === 'fileImport' ? renderer.mountFileImport : kind === 'accountImportAction' ? renderer.mountAccountImportAction : kind === 'accountConnection' ? renderer.mountAccountConnection : kind === 'linkChip' ? renderer.mountLinkChip : kind === 'importPreferences' ? renderer.mountImportPreferences : kind === 'directory' ? renderer.mountDirectory : kind === 'settingsForm' ? renderer.mountSettingsForm : kind === 'guide' ? renderer.mountSetupGuide : kind === 'credentials' ? renderer.mountCredentials : kind === 'provider' ? renderer.mountProvider : kind === 'tooltip' ? renderer.mountTooltip : renderer.mountCard)(host, props));
    } catch (error) {
      // Retain the server-rendered fallback and allow unrelated islands to mount.
      console.error('Settings component could not mount', error);
    }
  }));
}

function unmountWithin(element) {
  for (const [host, dispose] of roots) {
    if (host === element || element.contains?.(host)) {
      dispose();
      roots.delete(host);
    }
  }
}

// Alpine teleports popups (card ratings) to <body> without an htmx load event.
new MutationObserver(records => {
  for (const record of records) for (const node of record.addedNodes) {
    if (node.nodeType === 1 && (node.matches('[data-rating-stars-root]') || node.querySelector('[data-rating-stars-root]'))) mountWithin(node);
  }
}).observe(document.body, { childList: true });
document.addEventListener('htmx:beforeCleanupElement', (event) => unmountWithin(event.detail.elt));
document.addEventListener('htmx:load', (event) => mountWithin(event.detail.elt));
// A bfcache document retains its DOM and React state; disposing it would discard
// entered values on Back. Ordinary navigation/HTMX removal still disposes roots.
window.addEventListener('pagehide', event => { if (!event.persisted) unmountWithin(document); });
window.addEventListener('pageshow', () => mountWithin(document));
mountWithin(document);
