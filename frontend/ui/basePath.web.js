// Mount path of the app when it runs under BASE_URL (for example "/track").
// base.html publishes it in <meta name="floppy-base-path">; it is "" at the
// root. Root-absolute paths built in JavaScript bypass Django's URL helpers,
// so web callers run them through withBasePath. Web-only: native supplies its
// own server address.
export function readBasePath() {
  try {
    const meta = document.querySelector('meta[name="floppy-base-path"]');
    return normalizeBasePath(meta && meta.getAttribute('content'));
  } catch {
    return '';
  }
}

export function normalizeBasePath(value) {
  const trimmed = String(value || '').trim().replace(/\/+$/, '');
  return trimmed && trimmed !== '/' ? (trimmed.startsWith('/') ? trimmed : `/${trimmed}`) : '';
}

// Prefix a root-absolute path once; relative and absolute URLs pass through.
export function withBasePath(path, basePath) {
  const base = basePath === undefined ? readBasePath() : normalizeBasePath(basePath);
  const text = String(path);
  if (!base || !text.startsWith('/') || text.startsWith('//')) return text;
  if (text === base || text.startsWith(`${base}/`) || text.startsWith(`${base}?`)) return text;
  return `${base}${text}`;
}
