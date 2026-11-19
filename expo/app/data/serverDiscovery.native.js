import { collectFloppyServers, floppyServerFromService } from './serverDiscoveryCore';

const SERVICE_TYPE = { type: 'http', protocol: 'tcp', domain: 'local.' };
const SCAN_DURATION_MS = 5000;

export async function findFloppyServers() {
  let zeroconf;
  try {
    const Zeroconf = require('react-native-zeroconf').default;
    zeroconf = new Zeroconf();
    const permission = await zeroconf.checkLocalNetworkAccess({ ...SERVICE_TYPE, timeout: 3 });
    if (permission === 'denied') {
      zeroconf.removeDeviceListeners();
      return { supported: true, permissionDenied: true, servers: [] };
    }
  } catch {
    zeroconf?.removeDeviceListeners?.();
    return { supported: false, permissionDenied: false, servers: [] };
  }

  return new Promise(resolve => {
    const services = new Map();
    let finished = false;
    const finish = (error, permissionDenied = false) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      zeroconf.stop();
      zeroconf.removeAllListeners();
      zeroconf.removeDeviceListeners();
      resolve({
        supported: true,
        permissionDenied,
        error,
        servers: collectFloppyServers([...services.values()]),
      });
    };
    const timer = setTimeout(() => finish(), SCAN_DURATION_MS);
    zeroconf.on('resolved', service => {
      const candidate = floppyServerFromService(service);
      if (!candidate || (services.size >= 8 && !services.has(candidate.serverUrl))) return;
      services.set(candidate.serverUrl, service);
    });
    zeroconf.on('error', error => {
      if (error?.code === -65570 || /permission|local network/i.test(error?.message || '')) {
        finish(error, true);
      }
    });
    try {
      zeroconf.scan({ ...SERVICE_TYPE, resolveTimeout: 3 });
    } catch (error) {
      finish(error);
    }
  });
}
