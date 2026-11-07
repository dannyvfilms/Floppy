import { parse } from '@babel/parser';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const root = resolve(import.meta.dirname, '..');
const registryPath = 'docs/ui/architecture-registry.json';
const forbiddenGlobals = new Set(['window', 'document', 'navigator', 'location', 'localStorage', 'sessionStorage', 'htmx', 'Alpine', 'fetch', 'XMLHttpRequest', 'WebSocket', 'EventSource', 'globalThis', 'global', 'self', 'eval', 'Function']);
const forbiddenProps = new Set(['className', 'dangerouslySetInnerHTML', 'href', 'hrefAttrs', 'dataSet', 'onClick', 'onMouseEnter', 'onMouseLeave']);
const sourceExtensions = ['js', 'jsx', 'ts', 'tsx', 'mjs', 'cjs', 'mts', 'cts'];
// Application shell screens live beside the Expo project, not in the reusable
// presentation tree. They still receive the universal AST checks below.
export const isNativeAppShellPresentation = path => /^native-proof\/app\/.+\.(jsx|tsx)$/.test(path);
const hasEvidence = verification => ['web', 'ios', 'android'].every(platform => {
  const item = verification?.[platform];
  return item && ['verified', 'unverified'].includes(item.status) && typeof item.evidence === 'string' && item.evidence.trim().length > 0;
});
const digest = value => createHash('sha256').update(value).digest('hex');

function exportsRenderedComponent(program, name) {
  const declaration = program.body.filter(n => n.type === 'ExportNamedDeclaration').flatMap(n => {
    const d = n.declaration;
    if (d?.id?.name === name) return [d];
    return (d?.declarations || []).filter(item => item.id?.name === name);
  })[0];
  function renders(node) {
    if (!node || typeof node !== 'object') return false;
    if (node.type === 'JSXOpeningElement') return true;
    if (node.type === 'CallExpression' && (node.callee.name === 'createElement' || node.callee.property?.name === 'createElement')) return true;
    return Object.entries(node).some(([key, value]) => !['loc', 'start', 'end', 'extra'].includes(key) && (Array.isArray(value) ? value.some(renders) : typeof value === 'object' && renders(value)));
  }
  return renders(declaration);
}

export function legacyStatements(source) {
  const ast = parse(source, { sourceType: 'module', plugins: ['jsx', 'typescript'] });
  const clean = (key, value) => ['start', 'end', 'loc', 'extra', 'leadingComments', 'innerComments', 'trailingComments'].includes(key) ? undefined : value;
  return ast.program.body.map(statement => digest(JSON.stringify(statement, clean)));
}

// The parser examines actual syntax, not comments or substrings in identifiers.
export function inspectUniversal(source, file = 'component.jsx', { nativeAdapter = false, logic = false, adapter = false, dataLayer = false, shell = false } = {}) {
  const errors = [];
  let ast;
  try { ast = parse(source, { sourceType: 'module', plugins: ['jsx', 'typescript'] }); }
  catch (error) { return [`${file}: cannot parse: ${error.message}`]; }
  if (ast.program.directives.some(d => d.value.value === 'use dom')) errors.push(`${file}: Expo DOM components are not native presentation`);
  let nativeImport = false;
  let rendersElement = false;
  function fail(node, rule) { errors.push(`${file}:${node.loc?.start.line ?? '?'}: ${rule}`); }
  function walk(node, parent = null, key = '') {
    if (!node || typeof node !== 'object') return;
    if (['ImportDeclaration', 'ExportNamedDeclaration', 'ExportAllDeclaration'].includes(node.type) && node.source) {
      const name = node.source.value;
      if (name === 'react-native') { nativeImport = true; if (logic) fail(node, 'shared logic cannot depend on a renderer'); }
      else if (name !== 'react' && !name.startsWith('.') && !nativeAdapter) fail(node, `unapproved import '${name}'; move platform or transport dependencies into an adapter`);
      if (nativeAdapter && !name.startsWith('.') && !/^(?:react$|react-native(?:-|\/|$)|@react-native\/|expo(?:-|\/|$)|@expo\/)/.test(name)) fail(node, `unapproved native dependency '${name}'; use a reviewed native platform API`);
      if (nativeAdapter && /^(react-dom|react-native-web|react-native-webview|expo-dom|expo\/dom|htmx|alpinejs)(\/|$)/.test(name)) fail(node, `web-only import '${name}' cannot implement native presentation`);
      if (name.startsWith('.') && /\.(css|scss|sass|html|svg)$/.test(name)) fail(node, 'web asset import; provide cross-platform styles or an adapter');
      if (!nativeAdapter && name === 'react-native' && node.specifiers?.some(s => ['Platform', 'Linking', 'NativeModules', 'NativeEventEmitter', 'PermissionsAndroid'].includes(s.imported?.name))) fail(node, 'platform APIs belong in a platform adapter');
    }
    if (node.type === 'JSXOpeningElement') {
      rendersElement = true;
      if (logic || adapter) fail(node, 'shared logic and platform service adapters cannot render JSX');
      if (node.name.type === 'JSXIdentifier' && /^[a-z]/.test(node.name.name)) fail(node, `HTML element <${node.name.name}>; use a React Native primitive`);
      if (node.name.type === 'JSXIdentifier' && node.name.name === 'WebView') fail(node, 'WebView cannot substitute for native presentation');
    }
    if (node.type === 'JSXAttribute' && forbiddenProps.has(node.name.name)) fail(node, `web-only prop '${node.name.name}'; use a native-compatible contract or adapter`);
    if (node.type === 'JSXAttribute' && node.name.name === 'style' && node.value?.type === 'StringLiteral') fail(node, 'CSS string styles are web-only');
    if (node.type === 'CallExpression' && (node.callee.property?.name === 'createElement' || node.callee.name === 'createElement') && node.arguments[0]?.type === 'StringLiteral') fail(node, 'HTML createElement calls are web-only; use a React Native primitive');
    else if (node.type === 'CallExpression' && (node.callee.property?.name === 'createElement' || node.callee.name === 'createElement')) rendersElement = true;
    if (node.type === 'Identifier' && forbiddenGlobals.has(node.name) && !(dataLayer && node.name === 'fetch') && !(parent?.type === 'MemberExpression' && key === 'property' && !parent.computed) && !(parent?.type === 'ObjectProperty' && key === 'key' && !parent.computed)) fail(node, `'${node.name}' belongs in an adapter or data layer`);
    if (node.type === 'ImportExpression' || (node.type === 'CallExpression' && (node.callee.type === 'Import' || node.callee.name === 'require'))) fail(node, 'dynamic imports and require are not permitted in universal presentation');
    if (node.type === 'StringLiteral' && /(?:var\(--|\d(?:px|rem|vh|vw)\b)/.test(node.value)) fail(node, 'CSS variables and units are web-only; pass native-compatible theme values');
    if ((node.type === 'StringLiteral' || node.type === 'TemplateElement') && /\{(?:%|\{|#)/.test(node.type === 'TemplateElement' ? node.value.raw : node.value)) fail(node, 'Django template syntax belongs in the server adapter');
    if (node.type === 'ObjectProperty' && ['cursor', 'boxShadow', 'transition', 'animation'].includes(node.key?.name)) fail(node, 'web-only style property; use a platform adapter');
    if (node.type === 'ObjectProperty' && ['className', 'dangerouslySetInnerHTML'].includes(node.key?.name || node.key?.value)) fail(node, 'web-only presentation property');
    for (const [childKey, value] of Object.entries(node)) {
      if (['loc', 'start', 'end', 'extra', 'comments', 'leadingComments', 'trailingComments', 'innerComments', 'tokens'].includes(childKey)) continue;
      if (Array.isArray(value)) value.forEach(child => walk(child, node, childKey));
      else if (value && typeof value === 'object') walk(value, node, childKey);
    }
  }
  walk(ast.program);
  if (!logic && !adapter && !shell && !nativeImport) errors.push(`${file}: universal presentation must import React Native primitives`);
  if (!logic && !adapter && !rendersElement) errors.push(`${file}: native presentation must render an element; empty placeholders are not accepted`);
  return errors;
}

export function inspectWebAdapter(source, file, registeredPresentation = []) {
  const errors = [];
  let ast;
  try { ast = parse(source, { sourceType: 'module', plugins: ['jsx', 'typescript'] }); }
  catch (error) { return [`${file}: cannot parse: ${error.message}`]; }
  function walk(node, parent) {
    if (!node || typeof node !== 'object') return;
    const fail = reason => errors.push(`${file}:${node.loc?.start.line ?? '?'}: ${reason}`);
    if (node.type === 'JSXOpeningElement' && node.name.type === 'JSXIdentifier' && /^[a-z]/.test(node.name.name)) {
      const children = parent?.children?.filter(child => child.type !== 'JSXText' || child.value.trim());
      const safeStyle = attribute => attribute.name?.name === 'style' && attribute.value?.expression?.type === 'ObjectExpression' && attribute.value.expression.properties.length === 1 && attribute.value.expression.properties[0].key?.name === 'textDecoration' && attribute.value.expression.properties[0].value?.value === 'none';
      const link = node.name.name === 'a' && node.attributes.some(a => a.name?.name === 'href') && node.attributes.every(a => ['href', 'onMouseEnter', 'onMouseLeave'].includes(a.name?.name) || safeStyle(a)) && children?.length === 1 && children[0].type === 'JSXElement' && registeredPresentation.includes(children[0].openingElement.name.name);
      if (!link) fail('web adapters cannot define HTML presentation; mount a shared component');
    }
    if (node.type === 'JSXAttribute' && ['className', 'dangerouslySetInnerHTML'].includes(node.name.name)) fail('web adapters cannot own presentation styling or HTML');
    if (node.type === 'AssignmentExpression' && ['innerHTML', 'outerHTML'].includes(node.left?.property?.name)) fail('web adapters cannot generate HTML');
    if (node.type === 'CallExpression' && node.callee.type === 'MemberExpression') {
      const method = node.callee.property?.name;
      if (method === 'insertAdjacentHTML') fail('web adapters cannot generate HTML');
      if (method === 'createElement' && node.arguments[0]?.type === 'StringLiteral' && (node.callee.object?.name !== 'document' || !['form', 'input', 'canvas'].includes(node.arguments[0].value))) fail('web adapters cannot construct presentation elements');
    }
    if (node.type === 'CallExpression' && node.callee.name === 'createElement' && node.arguments[0]?.type === 'StringLiteral') fail('web adapters cannot construct presentation elements');
    for (const [key, value] of Object.entries(node)) if (!['loc', 'start', 'end', 'extra', 'leadingComments', 'trailingComments', 'innerComments'].includes(key)) {
      if (Array.isArray(value)) value.forEach(child => walk(child, node)); else if (value && typeof value === 'object') walk(value, node);
    }
  }
  walk(ast.program);
  return errors;
}

function filesUnder(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? filesUnder(path) : sourceExtensions.includes(entry.name.split('.').pop()) ? [relative(root, path)] : [];
  });
}

function baseRegistry() {
  const ref = process.env.UI_ARCH_BASE || 'HEAD';
  execFileSync('git', ['cat-file', '-e', `${ref}^{commit}`], { cwd: root, stdio: 'ignore' });
  try { execFileSync('git', ['cat-file', '-e', `${ref}:${registryPath}`], { cwd: root, stdio: 'ignore' }); }
  catch { return null; } // Initial adoption, before the registry exists in the base commit.
  return JSON.parse(execFileSync('git', ['show', `${ref}:${registryPath}`], { cwd: root, encoding: 'utf8' }));
}

export function validateRegistry(registry, base, sourceFiles, readSource, documents, readBaseSource) {
  const errors = [];
  const legacy = registry.legacy || {};
  const universal = registry.universal || {};
  const platform = registry.platform || {};
  const logic = registry.logic || {};
  const webAdapters = registry.web_adapters || {};
  const register = documents?.register ?? readFileSync(resolve(root, 'docs/ui/component-register.md'), 'utf8');
  const map = documents?.map ?? readFileSync(resolve(root, 'docs/ui/source-map.md'), 'utf8');
  for (const path of sourceFiles) {
    if ([legacy, universal, logic, platform, webAdapters].filter(group => group[path]).length > 1) errors.push(`${path}: a file cannot have multiple architecture classifications`);
  }
  if (base) {
    for (const [path, baseline] of Object.entries(legacy)) {
      if (JSON.stringify(base.legacy?.[path]) !== JSON.stringify(baseline)) errors.push(`${path}: adding or changing a legacy baseline is prohibited; implement universal presentation instead`);
    }
    for (const path of Object.keys(base.universal || {})) {
      if (!universal[path] && sourceFiles.includes(path)) errors.push(`${path}: universal classification cannot be downgraded; solve the incompatibility`);
    }
  }
  for (const path of sourceFiles) {
    const source = readSource(path);
    if (webAdapters[path]) {
      const entry = webAdapters[path];
      if (!/(?:^|\/)(?:mount(?:[A-Z][^/]*)?|index|webPalette|[^/]+\.web)\.(?:js|jsx|ts|tsx|mjs|cjs|mts|cts)$/.test(path)) errors.push(`${path}: web integration adapters must use an adapter or .web filename`);
      if (!entry.register || !entry.purpose || !register.includes(`### ${entry.register} —`) || !map.includes('`' + path + '`')) errors.push(`${path}: document the web adapter purpose, register owner and source-map path`);
      let names = [];
      try {
        const ast = parse(source, { sourceType: 'module', plugins: ['jsx', 'typescript'] });
        names = ast.program.body.filter(n => n.type === 'ImportDeclaration' && n.source.value.startsWith('.')).flatMap(n => {
          const destination = relative(root, resolve(root, dirname(path), n.source.value));
          const target = Object.entries(universal).find(([file]) => file === destination || sourceExtensions.some(ext => file === `${destination}.${ext}`));
          return target ? n.specifiers.filter(s => target[1].components.includes(s.imported?.name)).map(s => s.local.name) : [];
        });
      } catch { /* Parsing errors are reported by inspectWebAdapter. */ }
      errors.push(...inspectWebAdapter(source, path, names));
      continue;
    }
    if (legacy[path]) {
      const baseline = legacy[path];
      const previous = readBaseSource?.(path);
      if (previous === undefined ? digest(source) !== baseline.sha256 : source !== previous) {
        try {
          const available = previous === undefined ? [...baseline.statements] : legacyStatements(previous);
          const program = parse(source, { sourceType: 'module', plugins: ['jsx', 'typescript'] }).program;
          const previousProgram = previous === undefined ? null : parse(previous, { sourceType: 'module', plugins: ['jsx', 'typescript'] }).program;
          for (const statement of program.body) {
            const hash = legacyStatements(source.slice(statement.start, statement.end))[0];
            const index = available.indexOf(hash);
            if (index >= 0) { available.splice(index, 1); continue; }
            // A removed exported component may be redirected to a registered shared
            // implementation or its web adapter. No other legacy statement changes.
            const target = statement.source?.value;
            const resolved = target?.startsWith('.') && sourceFiles.find(candidate =>
              sourceExtensions.some(ext => candidate === `${relative(root, resolve(root, dirname(path), target))}.${ext}`) || candidate === relative(root, resolve(root, dirname(path), target)));
            const names = statement.specifiers?.map(specifier => specifier.exported?.name) || [];
            const oldExports = previousProgram?.body.filter(node => node.type === 'ExportNamedDeclaration' && node.declaration?.id).map(node => node.declaration.id.name) || [];
            const owner = universal[resolved] || webAdapters[resolved];
            const direct = universal[resolved] || (webAdapters[resolved] && resolved && parse(readSource(resolved), { sourceType: 'module', plugins: ['jsx', 'typescript'] }).program.body.some(node => {
              if (node.type !== 'ImportDeclaration' || !node.source.value.startsWith('.')) return false;
              const destination = relative(root, resolve(root, dirname(resolved), node.source.value));
              return Object.entries(universal).some(([file, entry]) => (file === destination || sourceExtensions.some(ext => file === `${destination}.${ext}`)) && entry.register === owner.register && node.specifiers.some(specifier => entry.components.includes(specifier.imported?.name) && names.includes(specifier.imported.name)));
            }));
            if (statement.type === 'ExportNamedDeclaration' && !statement.declaration && names.length && statement.specifiers.every(specifier => specifier.type === 'ExportSpecifier' && specifier.local.name === specifier.exported.name) && names.every(name => oldExports.includes(name)) && owner && direct && (universal[resolved] ? names.every(name => owner.components.includes(name)) : names.every(name => parse(readSource(resolved), { sourceType: 'module', plugins: ['jsx', 'typescript'] }).program.body.some(node => node.type === 'ExportNamedDeclaration' && node.declaration?.id?.name === name)))) continue;
            errors.push(`${path}: a legacy declaration changed or was added; migrate the affected component into universal presentation instead`); break;
          }
        } catch { errors.push(`${path}: changed legacy source cannot be parsed`); }
      }
      continue;
    }
    if (/\.(web|native|ios|android)\.(js|jsx|ts|tsx|mjs|cjs|mts|cts)$/.test(path)) {
      const entry = platform[path];
      if (!entry || !['presentation', 'adapter'].includes(entry.kind) || !entry.register || !entry.purpose || !Array.isArray(entry.components) || !entry.components.length || !hasEvidence(entry.verification)) errors.push(`${path}: register platform kind, components, purpose and web/iOS/Android evidence in ${registryPath}`);
      else if (!register.includes(`### ${entry.register} —`) || !map.includes('`' + path + '`')) errors.push(`${path}: add its register ID and source-map path`);
      const prefix = path.replace(/\.(web|native|ios|android)\.(js|jsx|ts|tsx|mjs|cjs|mts|cts)$/, '');
      const candidates = suffix => sourceExtensions.some(ext => sourceFiles.includes(`${prefix}.${suffix}.${ext}`));
      if (!candidates('web') || !(candidates('native') || (candidates('ios') && candidates('android')))) errors.push(`${path}: platform-specific presentation requires web and native (or iOS and Android) counterparts`);
      const partners = Object.entries(platform).filter(([other]) => other !== path && other.replace(/\.(web|native|ios|android)\.(js|jsx|ts|tsx|mjs|cjs|mts|cts)$/, '') === prefix);
      if (entry?.components && partners.some(([, other]) => other.kind !== entry.kind || JSON.stringify([...(other.components || [])].sort()) !== JSON.stringify([...entry.components].sort()))) errors.push(`${path}: platform counterparts must register the same component contract and kind`);
      try {
        const ast = parse(source, { sourceType: 'module', plugins: ['jsx', 'typescript'] });
        if (entry?.kind === 'adapter' && /\.web\./.test(path)) {
          const noJsx = node => {
            if (!node || typeof node !== 'object') return;
            if (node.type === 'JSXElement' || node.type === 'JSXFragment') errors.push(`${path}: a platform service adapter cannot render JSX`);
            for (const [key, value] of Object.entries(node)) if (!['loc', 'start', 'end', 'extra'].includes(key)) {
              if (Array.isArray(value)) value.forEach(noJsx); else if (value && typeof value === 'object') noJsx(value);
            }
          };
          noJsx(ast.program);
        }
        const exported = new Set(ast.program.body.flatMap(n => n.type === 'ExportNamedDeclaration' ? [n.declaration?.id?.name, ...(n.declaration?.declarations || []).map(d => d.id?.name), ...(n.specifiers || []).map(s => s.exported?.name)] : []));
        for (const name of entry?.components || []) if (!exported.has(name) || !register.includes(name)) errors.push(`${path}: component '${name}' must be exported and named in the component register`);
        if (entry?.kind === 'presentation') for (const name of entry.components) if (!exportsRenderedComponent(ast.program, name)) errors.push(`${path}: '${name}' must directly export an implementation that renders an element`);
        if (!/\.web\.(js|jsx|ts|tsx|mjs|cjs|mts|cts)$/.test(path)) {
          for (const declaration of ast.program.body.filter(n => ['ImportDeclaration', 'ExportNamedDeclaration', 'ExportAllDeclaration'].includes(n.type) && n.source?.value.startsWith('.'))) {
            const imported = resolve(root, dirname(path), declaration.source.value);
            const resolved = [imported, ...sourceExtensions.map(ext => `${imported}.${ext}`)].filter(existsSync).map(candidate => relative(root, candidate));
            if (!resolved.some(candidate => universal[candidate] || logic[candidate] || (platform[candidate] && !/\.web\./.test(candidate)))) errors.push(`${path}: native dependency '${declaration.source.value}' is not a registered native-compatible module`);
          }
        }
      } catch { errors.push(`${path}: platform source cannot be parsed`); }
      if (!/\.web\.(js|jsx|ts|tsx|mjs|cjs|mts|cts)$/.test(path)) errors.push(...inspectUniversal(source, path, { nativeAdapter: true, adapter: entry?.kind === 'adapter' }));
      continue;
    }
    const isLogic = Boolean(logic[path]);
    const entry = universal[path] || logic[path];
    if (!entry || !Array.isArray(entry.components) || !entry.components.length || !entry.register || !entry.verification) {
      errors.push(`${path}: register universal components, register ID, and separate web/iOS/Android verification in ${registryPath}`);
      continue;
    }
    if (!hasEvidence(entry.verification)) errors.push(`${path}: web, iOS and Android status and evidence must each be recorded`);
    errors.push(...inspectUniversal(source, path, { logic: isLogic }));
    if (!register.includes(`### ${entry.register} —`) || !map.includes('`' + path + '`')) errors.push(`${path}: add its register ID and source-map path`);
    let ast;
    try { ast = parse(source, { sourceType: 'module', plugins: ['jsx', 'typescript'] }); } catch { continue; }
    const exports = new Set(ast.program.body.flatMap(n => n.type === 'ExportNamedDeclaration' ? [n.declaration?.id?.name, ...(n.declaration?.declarations || []).map(d => d.id?.name), ...(n.specifiers || []).map(s => s.exported?.name)] : []));
    for (const name of entry.components) if (!exports.has(name) || !register.includes(name)) errors.push(`${path}: component '${name}' must be exported and named in the component register`);
    if (!isLogic) for (const name of entry.components) if (!exportsRenderedComponent(ast.program, name)) errors.push(`${path}: '${name}' must directly export an implementation that renders an element`);
    for (const declaration of ast.program.body.filter(n => ['ImportDeclaration', 'ExportNamedDeclaration', 'ExportAllDeclaration'].includes(n.type) && n.source?.value.startsWith('.'))) {
      const imported = resolve(root, dirname(path), declaration.source.value);
      const candidates = [imported, ...sourceExtensions.map(ext => `${imported}.${ext}`)].filter(existsSync);
      if (!candidates.length || !candidates.some(candidate => logic[relative(root, candidate)] || (!isLogic && universal[relative(root, candidate)]))) errors.push(`${path}: relative dependency '${declaration.source.value}' is not registered shared presentation or logic; move platform details to an adapter`);
    }
  }
  for (const path of Object.keys(legacy)) if (!sourceFiles.includes(path)) errors.push(`${path}: remove stale legacy baseline entry`);
  for (const path of Object.keys(universal)) if (!sourceFiles.includes(path)) errors.push(`${path}: remove stale universal registration`);
  for (const path of Object.keys(platform)) if (!sourceFiles.includes(path)) errors.push(`${path}: remove stale platform registration`);
  for (const path of Object.keys(logic)) if (!sourceFiles.includes(path)) errors.push(`${path}: remove stale logic registration`);
  for (const path of Object.keys(webAdapters)) if (!sourceFiles.includes(path)) errors.push(`${path}: remove stale web adapter registration`);
  return errors;
}

function main() {
  const registry = JSON.parse(readFileSync(resolve(root, registryPath), 'utf8'));
  const files = filesUnder(resolve(root, 'frontend'));
  const base = baseRegistry();
  const readBase = base ? path => {
    const ref = `${process.env.UI_ARCH_BASE || 'HEAD'}:${path}`;
    try { execFileSync('git', ['cat-file', '-e', ref], { cwd: root, stdio: 'ignore' }); }
    catch { return undefined; }
    return execFileSync('git', ['show', ref], { cwd: root, encoding: 'utf8' });
  } : undefined;
  const errors = validateRegistry(registry, base, files, path => readFileSync(resolve(root, path), 'utf8'), undefined, readBase);
  errors.push(...inspectUniversal(readFileSync(resolve(root, 'native-proof/App.js'), 'utf8'), 'native-proof/App.js'));
  const repositoryFiles = execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard', '-z'], { cwd: root, encoding: 'utf8' }).split('\0');
  for (const path of repositoryFiles) {
    if (!/\.(jsx|tsx)$/.test(path) || path.startsWith('frontend/')) continue;
    if (isNativeAppShellPresentation(path)) {
      errors.push(...inspectUniversal(readFileSync(resolve(root, path), 'utf8'), path, { nativeAdapter: true, shell: true }));
      continue;
    }
    errors.push(`${path}: place React presentation in frontend/ so it is registered and checked`);
  }
  if (base && files.some(path => (registry.universal?.[path] || registry.platform?.[path] || registry.web_adapters?.[path] || registry.legacy?.[path]) && readFileSync(resolve(root, path), 'utf8') !== readBase(path))) {
    for (const doc of ['docs/ui/component-register.md', 'docs/ui/source-map.md']) {
      if (readFileSync(resolve(root, doc), 'utf8') === readBase(doc)) errors.push(`${doc}: update the ledger when shared UI presentation changes`);
    }
  }
  if (errors.length) { console.error(errors.join('\n')); process.exitCode = 1; }
  else console.log(`UI architecture verified: ${Object.keys(registry.universal).length} universal files; ${Object.keys(registry.legacy).length} frozen legacy files; ${Object.keys(registry.web_adapters || {}).length} web adapters.`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) main();
