// Development proof transport. Production authentication and storage need a
// separately designed platform boundary.
export async function loadMedia(server, token) {
  const base = new URL(server.trim());
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(base.hostname);
  if ((base.protocol !== 'https:' && !(base.protocol === 'http:' && loopback)) || base.username || base.password || base.search || base.hash) {
    throw new Error('Use HTTPS, or HTTP on localhost, without credentials, query or fragment.');
  }
  const endpoint = new URL(`${base.pathname.replace(/\/$/, '')}/api/v1/media?limit=12`, base.origin);
  const response = await fetch(endpoint.toString(), { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`Request failed (${response.status}).`);
  const data = await response.json();
  return data.results.filter((entry) => entry.item?.title).map((entry) => ({
    key: String(entry.id), title: entry.item.title,
    image: entry.item.image ? new URL(entry.item.image, base.origin).toString() : null,
  }));
}
