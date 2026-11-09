#!/usr/bin/env node
// Enforce the web ↔ Expo page registry contract.
//
//   node scripts/check_page_parity.mjs           # report gaps; exit 0
//   node scripts/check_page_parity.mjs --strict  # fail while any page is legacy
//
// A `shared` page must have one view file imported by both its web adapter and
// its native screen. `legacy` pages are counted so a parity claim is honest.
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { pages } from '../frontend/pages/registry.js';

const strict = process.argv.includes('--strict');
const root = process.cwd();
const problems = [];

function read(path) {
  const full = resolve(root, path);
  return existsSync(full) ? readFileSync(full, 'utf8') : '';
}

function importsView(source, viewPath) {
  const base = viewPath.split('/').pop().replace(/\.jsx?$/, '');
  const pattern = new RegExp(`from\\s+['"][^'"]*${base}(?:\\.jsx?)?['"]`);
  return pattern.test(source);
}

const seen = new Set();
for (const page of Object.values(pages)) {
  if (seen.has(page.id)) problems.push(`duplicate page id: ${page.id}`);
  seen.add(page.id);
  if (!page.webRoute || !page.nativeScreen) problems.push(`${page.id}: missing webRoute/nativeScreen`);
  if (page.status === 'shared') {
    for (const key of ['view', 'webAdapter']) {
      if (!page[key]) problems.push(`${page.id}: shared page is missing ${key}`);
      else if (!existsSync(resolve(root, page[key]))) problems.push(`${page.id}: missing ${page[key]}`);
    }
    if (!page.view) continue;
    if (!importsView(read(page.webAdapter), page.view)) {
      problems.push(`${page.id}: web adapter does not import the shared view ${page.view}`);
    }
    const nativeFile = page.nativeAdapter || page.nativeScreen;
    if (page.nativeAdapter && !existsSync(resolve(root, page.nativeAdapter))) {
      problems.push(`${page.id}: missing native adapter ${page.nativeAdapter}`);
    } else if (!importsView(read(nativeFile), page.view)) {
      problems.push(`${page.id}: native screen/adapter does not import the shared view ${page.view}`);
    }
  }
}

const legacy = Object.values(pages).filter(page => page.status !== 'shared');
const shared = Object.values(pages).filter(page => page.status === 'shared');
console.log(`Shared pages: ${shared.length}`);
for (const page of shared) console.log(`  ✓ ${page.id}`);
console.log(`Legacy pages: ${legacy.length}`);
for (const page of legacy) console.log(`  · ${page.id}`);
if (problems.length) {
  console.error('\nPage parity contract problems:');
  for (const problem of problems) console.error(`  ✗ ${problem}`);
  process.exit(1);
}
if (strict && legacy.length) {
  console.error(`\nSTRICT: ${legacy.length} page(s) are still legacy; parity is not complete.`);
  process.exit(1);
}
console.log('\nPage registry contract OK.');
