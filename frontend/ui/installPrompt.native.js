import { Linking } from 'react-native';

const INSTALL_GUIDE_URL = 'https://github.com/dannyvfilms/Floppy/wiki/2.-User-Guide#installing-floppy-on-your-phone';

/** Native app install state. A bundled app is already installed; the browser
 * install prompt has no equivalent, so the shared card shows launch/update copy
 * and the guide still opens in the platform browser. */
export function getInstallState() {
  return { platform: 'native', canInstall: false, standalone: true, installed: true, supported: false };
}

export function subscribeInstallState(listener) {
  listener(getInstallState());
  return () => {};
}

export async function requestInstall() {
  return { outcome: 'unavailable' };
}

export async function openInstallGuide() {
  try {
    await Linking.openURL(INSTALL_GUIDE_URL);
    return true;
  } catch (error) {
    return false;
  }
}
