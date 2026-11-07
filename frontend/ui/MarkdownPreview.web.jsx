import React from 'react';

const SAFE_PROTOCOLS = ['http:', 'https:', 'mailto:'];

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function sanitizeLink(href) {
  if (!href) return null;
  try {
    const url = new URL(href, window.location.origin);
    if (SAFE_PROTOCOLS.includes(url.protocol)) return url.href;
  } catch (error) {
    // Invalid URLs render as plain text.
  }
  return null;
}

const getRenderer = (() => {
  let renderer = null;
  return () => {
    if (!window.marked) return null;
    if (renderer) return renderer;
    renderer = new window.marked.Renderer();
    renderer.html = html => escapeHtml(html);
    renderer.heading = (text, level) =>
      `<h${level} class="text-sm font-semibold text-gray-100 mb-2">${text}</h${level}>`;
    renderer.paragraph = text => `<p class="text-sm text-gray-200 mb-2">${text}</p>`;
    renderer.list = (body, ordered) => {
      const listClass = ordered ? 'list-decimal' : 'list-disc';
      const tag = ordered ? 'ol' : 'ul';
      return `<${tag} class="${listClass} list-inside text-sm text-gray-200 mb-2 space-y-1">${body}</${tag}>`;
    };
    renderer.blockquote = quote =>
      `<blockquote class="border-l-2 border-gray-600 pl-3 italic text-gray-300 mb-2">${quote}</blockquote>`;
    renderer.code = code =>
      `<pre class="bg-[#1f2328] text-gray-200 text-xs rounded-md p-3 mb-2 overflow-x-auto"><code>${escapeHtml(code)}</code></pre>`;
    renderer.codespan = code =>
      `<code class="bg-[var(--color-surface-dim)] text-[var(--color-text)] text-xs rounded px-1 py-0.5">${escapeHtml(code)}</code>`;
    renderer.hr = () => '<hr class="border-[var(--color-surface-border)] my-3" />';
    renderer.link = (href, title, text) => {
      const safeHref = sanitizeLink(href);
      if (!safeHref) return text;
      const titleAttr = title ? ` title="${escapeHtml(title)}"` : '';
      return `<a class="text-[var(--color-link)] hover:text-[var(--color-link-hover)] underline" href="${escapeHtml(safeHref)}" target="_blank" rel="noopener noreferrer"${titleAttr}>${text}</a>`;
    };
    renderer.image = (_href, _title, text) =>
      `<span class="text-gray-400">[${escapeHtml(window.gettext ? window.gettext('image') : 'image')}${text ? `: ${escapeHtml(text)}` : ''}]</span>`;
    window.marked.setOptions({ gfm: true, breaks: true, mangle: false, headerIds: false });
    return renderer;
  };
})();

export function renderMarkdownHtml(input) {
  const renderer = getRenderer();
  if (renderer && window.marked && typeof window.marked.parse === 'function') {
    return window.marked.parse(String(input || ''), { renderer });
  }
  return escapeHtml(input || '').replace(/\n/g, '<br>');
}

export function MarkdownPreview({ markdown, labels = {}, palette: _palette }) {
  const source = String(markdown ?? '');
  if (!source.trim()) {
    return <div className="text-sm text-gray-400">{labels.emptyPreview || 'Nothing to preview yet.'}</div>;
  }
  return <div
    className="text-sm text-[var(--color-text-secondary)]"
    dangerouslySetInnerHTML={{ __html: renderMarkdownHtml(source) }} />;
}
