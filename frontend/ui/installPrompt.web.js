/** Browser install adapter. The head script in base.html owns the
 * beforeinstallprompt capture so the event is never missed; this adapter reads
 * that shared state, subscribes to its announcements and consumes the one-use
 * prompt exactly like the About page.
 */
const INSTALL_GUIDE_URL = 'https://github.com/dannyvfilms/Floppy/wiki/2.-User-Guide#installing-floppy-on-your-phone';

function detectPlatform() {
  const ua = navigator.userAgent || '';
  if (/Android/i.test(ua)) return 'android';
  const iosDevice = /iPad|iPhone|iPod/.test(ua);
  const iPadDesktopUA = /Macintosh/.test(ua) && navigator.maxTouchPoints > 1;
  return iosDevice || iPadDesktopUA ? 'ios' : 'desktop';
}

function isStandalone() {
  if (window.floppyPwa?.isStandalone) return window.floppyPwa.isStandalone();
  return window.matchMedia?.('(display-mode: standalone)').matches
    || window.navigator.standalone === true;
}

export function getInstallState() {
  const pwa = window.floppyPwa;
  const standalone = isStandalone();
  return {
    platform: detectPlatform(),
    canInstall: Boolean(pwa?.deferredPrompt) && !standalone,
    standalone,
    installed: Boolean(pwa?.installed) || standalone,
    supported: Boolean(pwa),
  };
}

export function subscribeInstallState(listener) {
  const update = () => listener(getInstallState());
  update();
  window.addEventListener('floppy:install-availability', update);
  window.addEventListener('appinstalled', update);
  return () => {
    window.removeEventListener('floppy:install-availability', update);
    window.removeEventListener('appinstalled', update);
  };
}

export async function requestInstall() {
  const pwa = window.floppyPwa;
  const prompt = pwa?.deferredPrompt;
  if (!prompt) return { outcome: 'unavailable' };
  pwa.deferredPrompt = null;
  try {
    await prompt.prompt();
    const choice = await prompt.userChoice;
    return { outcome: choice.outcome === 'accepted' ? 'accepted' : 'dismissed' };
  } catch (error) {
    return { outcome: 'failed' };
  }
}

export async function openInstallGuide() {
  const opened = window.open(INSTALL_GUIDE_URL, '_blank', 'noopener,noreferrer');
  if (opened) opened.opener = null;
  return true;
}
