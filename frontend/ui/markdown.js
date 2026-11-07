const SAFE_SCHEME = /^[a-z][a-z0-9+.-]*:/i;
const SAFE_ABSOLUTE = /^(?:https?:|mailto:)/i;

export function normalizeSelection(selection, length) {
  const limit = Math.max(0, Number(length) || 0);
  const start = Math.min(Math.max(0, Number(selection?.start) || 0), limit);
  const end = Math.min(Math.max(start, Number(selection?.end) || start), limit);
  return { start, end };
}

export function wrapMarkdownSelection(value, selection, before, after, placeholder = '') {
  const text = String(value ?? '');
  const { start, end } = normalizeSelection(selection, text.length);
  const selected = text.slice(start, end) || placeholder;
  const nextValue = text.slice(0, start) + before + selected + after + text.slice(end);
  const cursorStart = start + before.length;
  return {
    value: nextValue,
    selection: { start: cursorStart, end: cursorStart + selected.length },
  };
}

export function prefixMarkdownLines(value, selection, prefix, ordered = false) {
  const text = String(value ?? '');
  const { start, end } = normalizeSelection(selection, text.length);
  const lineStart = text.lastIndexOf('\n', Math.max(0, start - 1)) + 1;
  const lineEndIndex = text.indexOf('\n', end);
  const lineEnd = lineEndIndex === -1 ? text.length : lineEndIndex;
  const block = text.slice(lineStart, lineEnd);
  const lines = block.split('\n');
  const nextLines = lines.map((line, index) => {
    if (!line.trim()) return line;
    return `${ordered ? `${index + 1}. ` : prefix}${line}`;
  });
  const nextBlock = nextLines.join('\n');
  const nextValue = text.slice(0, lineStart) + nextBlock + text.slice(lineEnd);
  return {
    value: nextValue,
    selection: { start: lineStart, end: lineStart + nextBlock.length },
  };
}

export function applyMarkdownAction(value, selection, action, placeholders = {}) {
  const text = String(value ?? '');
  switch (action) {
    case 'heading':
      return prefixMarkdownLines(text, selection, '# ');
    case 'bold':
      return wrapMarkdownSelection(text, selection, '**', '**', placeholders.bold || 'bold text');
    case 'italic':
      return wrapMarkdownSelection(text, selection, '*', '*', placeholders.italic || 'italic text');
    case 'code': {
      const { start, end } = normalizeSelection(selection, text.length);
      const selected = text.slice(start, end);
      return selected.includes('\n')
        ? wrapMarkdownSelection(text, selection, '```\n', '\n```', placeholders.code || 'code')
        : wrapMarkdownSelection(text, selection, '`', '`', placeholders.code || 'code');
    }
    case 'link': {
      const { start, end } = normalizeSelection(selection, text.length);
      const selected = text.slice(start, end) || placeholders.link || 'link text';
      const url = 'https://';
      const insertion = `[${selected}](${url})`;
      const nextValue = text.slice(0, start) + insertion + text.slice(end);
      const urlStart = start + selected.length + 3;
      return {
        value: nextValue,
        selection: { start: urlStart, end: urlStart + url.length },
      };
    }
    case 'quote':
      return prefixMarkdownLines(text, selection, '> ');
    case 'ul':
      return prefixMarkdownLines(text, selection, '- ');
    case 'ol':
      return prefixMarkdownLines(text, selection, '', true);
    default:
      return { value: text, selection: normalizeSelection(selection, text.length) };
  }
}

export function safeMarkdownHref(href) {
  const value = String(href ?? '').trim();
  if (!value || value.startsWith('//')) return null;
  if (SAFE_ABSOLUTE.test(value)) return value;
  if (SAFE_SCHEME.test(value)) return null;
  return value;
}

function isBlockStart(line) {
  return /^\s*```/.test(line)
    || /^\s*#{1,6}\s+/.test(line)
    || /^\s*>\s?/.test(line)
    || /^\s*[-*+]\s+/.test(line)
    || /^\s*\d+[.)]\s+/.test(line)
    || /^\s*(?:---+|\*\*\*+|___+)\s*$/.test(line);
}

export function markdownBlocks(value) {
  const lines = String(value ?? '').replace(/\r\n?/g, '\n').split('\n');
  const blocks = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    const fence = /^\s*```(.*)$/.exec(line);
    if (fence) {
      const code = [];
      index += 1;
      while (index < lines.length && !/^\s*```/.test(lines[index])) {
        code.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push({ type: 'code', language: fence[1].trim(), text: code.join('\n') });
      continue;
    }
    const heading = /^\s*(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2].trim() });
      index += 1;
      continue;
    }
    if (/^\s*(?:---+|\*\*\*+|___+)\s*$/.test(line)) {
      blocks.push({ type: 'hr' });
      index += 1;
      continue;
    }
    if (/^\s*>\s?/.test(line)) {
      const quote = [];
      while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
        quote.push(lines[index].replace(/^\s*>\s?/, ''));
        index += 1;
      }
      blocks.push({ type: 'quote', text: quote.join('\n') });
      continue;
    }
    if (/^\s*[-*+]\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*+]\s+/, ''));
        index += 1;
      }
      blocks.push({ type: 'list', ordered: false, items });
      continue;
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^\s*\d+[.)]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+[.)]\s+/, ''));
        index += 1;
      }
      blocks.push({ type: 'list', ordered: true, items });
      continue;
    }
    const paragraph = [];
    while (index < lines.length && lines[index].trim() && !isBlockStart(lines[index])) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ type: 'paragraph', text: paragraph.join('\n') });
  }
  return blocks;
}

export function inlineMarkdown(value) {
  const source = String(value ?? '');
  const tokens = [];
  let index = 0;
  while (index < source.length) {
    const rest = source.slice(index);
    let match = /^`([^`]+)`/.exec(rest);
    if (match) {
      tokens.push({ type: 'code', text: match[1] });
      index += match[0].length;
      continue;
    }
    match = /^\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/.exec(rest);
    if (match) {
      tokens.push({ type: 'link', text: match[1] || match[2], href: safeMarkdownHref(match[2]) });
      index += match[0].length;
      continue;
    }
    match = /^(\*\*|__)([\s\S]+?)\1/.exec(rest);
    if (match) {
      tokens.push({ type: 'bold', text: match[2] });
      index += match[0].length;
      continue;
    }
    match = /^(\*|_)([^*_\n]+?)\1/.exec(rest);
    if (match) {
      tokens.push({ type: 'italic', text: match[2] });
      index += match[0].length;
      continue;
    }
    const next = rest.search(/[`[*_]/);
    const length = next === -1 ? rest.length : Math.max(1, next);
    tokens.push({ type: 'text', text: rest.slice(0, length) });
    index += length;
  }
  return tokens;
}
