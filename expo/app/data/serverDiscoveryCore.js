function validIPv4(value) {
  if (typeof value !== 'string') return false;
  const parts = value.split('.');
  return parts.length === 4 && parts.every(part => /^\d{1,3}$/.test(part) && Number(part) <= 255);
}

export function floppyServerFromService(service) {
  if (service?.txt?.floppy !== '1') return null;
  const address = (service.ipv4 || []).find(validIPv4);
  const port = Number(service.port);
  if (!address || !Number.isInteger(port) || port < 1 || port > 65535) return null;
  return {
    name: service.name || 'Floppy',
    address,
    port,
    serverUrl: `http://${address}:${port}`,
  };
}

export function collectFloppyServers(services) {
  const results = new Map();
  for (const service of services) {
    const server = floppyServerFromService(service);
    if (server) results.set(server.serverUrl, server);
  }
  return [...results.values()];
}

export async function verifyDiscoveredServers(candidates, fetchConfig, { limit = 8, timeoutMs = 5000 } = {}) {
  const checks = await Promise.allSettled(candidates.slice(0, limit).map(async candidate => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const config = await fetchConfig({ serverUrl: candidate.serverUrl, signal: controller.signal });
      return { ...candidate, config };
    } finally {
      clearTimeout(timeout);
    }
  }));
  return checks.filter(result => result.status === 'fulfilled').map(result => result.value);
}
