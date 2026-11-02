import './settings-card.css';
import '../ui/controls.css';
import '../ui/alphabet.css';
import '../providers/provider-page.css';

// One small loader on every page; React/RNW are fetched only when a card appears.
const roots = new Map();
const renderers = {};
const selector = '[data-alphabet-root], [data-settings-card-root], [data-provider-root], [data-provider-credentials-root], [data-setup-guide-root], [data-settings-form-root], [data-provider-directory-root], [data-tooltip-root], [data-import-preferences-root], [data-link-chip-root], [data-account-connection-root], [data-account-import-action-root], [data-file-import-root], [data-backup-status-root]';
const hostsWithin = (element) => [
  ...(element.matches?.(selector) ? [element] : []),
  ...element.querySelectorAll?.(selector) || [],
].filter(host => (host.matches('[data-provider-root]') || !host.closest('[data-provider-root]')) &&
  (host.matches('[data-import-preferences-root]') || !host.closest('[data-import-preferences-root]')) &&
  (host.matches('[data-account-connection-root]') || !host.closest('[data-account-connection-root]')));

async function mountWithin(element) {
  const hosts = hostsWithin(element);
  if (!hosts.length) return;
  for (const host of hosts) {
    const kind = host.matches('[data-alphabet-root]') ? 'alphabet' : host.matches('[data-backup-status-root]') ? 'backupStatus' : host.matches('[data-file-import-root]') ? 'fileImport' : host.matches('[data-account-import-action-root]') ? 'accountImportAction' : host.matches('[data-account-connection-root]') ? 'accountConnection' : host.matches('[data-link-chip-root]') ? 'linkChip' : host.matches('[data-import-preferences-root]') ? 'importPreferences' : host.matches('[data-tooltip-root]') ? 'tooltip' : host.matches('[data-provider-directory-root]') ? 'directory' : host.matches('[data-settings-form-root]') ? 'settingsForm' : host.matches('[data-setup-guide-root]') ? 'guide' : host.matches('[data-provider-credentials-root]') ? 'credentials' : host.matches('[data-provider-root]') ? 'provider' : 'card';
    try {
      renderers[kind] ??= (kind === 'alphabet' ? import('../ui/mountAlphabet.jsx') : kind === 'backupStatus' ? import('./BackupStatus.jsx') : kind === 'fileImport' ? import('../providers/FileImport.jsx') : (kind === 'accountConnection' || kind === 'accountImportAction') ? import('../providers/AccountConnection.jsx') : kind === 'importPreferences' ? import('../providers/ImportPreferences.jsx') : kind === 'directory' ? import('../providers/Directory.jsx') : kind === 'settingsForm' ? import('../providers/SettingsForm.jsx') : kind === 'guide' ? import('../providers/SetupGuide.jsx') : kind === 'credentials' ? import('../providers/Credentials.jsx') : kind === 'provider' ? import('../providers/mount.jsx') : import('./mount.jsx'))
        .catch(error => { delete renderers[kind]; throw error; });
      const renderer = await renderers[kind];
      if (!host.isConnected || roots.has(host)) continue;
      const script = document.getElementById(host.dataset.propsId);
      if (!script || !host.parentElement.contains(script)) continue;
      const props = JSON.parse(script.textContent);
      roots.set(host, (kind === 'alphabet' ? renderer.mountAlphabet : kind === 'backupStatus' ? renderer.mountBackupStatus : kind === 'fileImport' ? renderer.mountFileImport : kind === 'accountImportAction' ? renderer.mountAccountImportAction : kind === 'accountConnection' ? renderer.mountAccountConnection : kind === 'linkChip' ? renderer.mountLinkChip : kind === 'importPreferences' ? renderer.mountImportPreferences : kind === 'directory' ? renderer.mountDirectory : kind === 'settingsForm' ? renderer.mountSettingsForm : kind === 'guide' ? renderer.mountSetupGuide : kind === 'credentials' ? renderer.mountCredentials : kind === 'provider' ? renderer.mountProvider : kind === 'tooltip' ? renderer.mountTooltip : renderer.mountCard)(host, props));
    } catch (error) {
      // Retain the server-rendered fallback and allow unrelated islands to mount.
      console.error('Settings component could not mount', error);
    }
  }
}

function unmountWithin(element) {
  for (const [host, dispose] of roots) {
    if (host === element || element.contains?.(host)) {
      dispose();
      roots.delete(host);
    }
  }
}

document.addEventListener('htmx:beforeCleanupElement', (event) => unmountWithin(event.detail.elt));
document.addEventListener('htmx:load', (event) => mountWithin(event.detail.elt));
// A bfcache document retains its DOM and React state; disposing it would discard
// entered values on Back. Ordinary navigation/HTMX removal still disposes roots.
window.addEventListener('pagehide', event => { if (!event.persisted) unmountWithin(document); });
window.addEventListener('pageshow', () => mountWithin(document));
mountWithin(document);
