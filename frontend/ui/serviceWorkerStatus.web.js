/** Browser service-worker/static-cache status. Registration itself stays in
 * base.html; this adapter only reads the resulting registration, controller and
 * floppy cache names for presentation. */
export async function getCacheStatus() {
  if (!('serviceWorker' in navigator)) {
    return { supported: false, reason: 'unsupported', cacheNames: [] };
  }
  try {
    const registration = await navigator.serviceWorker.getRegistration();
    const cacheNames = 'caches' in window
      ? (await window.caches.keys()).filter(name => name.startsWith('floppy-'))
      : [];
    return {
      supported: true,
      registered: Boolean(registration),
      active: Boolean(registration?.active),
      controlled: Boolean(navigator.serviceWorker.controller),
      scope: registration?.scope || '',
      cacheNames,
    };
  } catch (error) {
    return { supported: false, reason: 'unavailable', cacheNames: [] };
  }
}
