import { build } from 'esbuild';
import { readFile, readdir, mkdir, writeFile, rm } from 'node:fs/promises';
import { basename, resolve } from 'node:path';

const outdir = resolve('src/static/ui');
const result = await build({
  entryPoints: { 'settings-islands': 'frontend/settings/index.js' },
  outdir, bundle: true, splitting: true, format: 'esm', minify: true,
  target: ['es2022'], jsx: 'automatic', legalComments: 'external',
  alias: { 'react-native': 'react-native-web' },
  define: { 'process.env.NODE_ENV': '"production"' },
  chunkNames: '[name]-[hash]', write: false,
});
const files = new Map(result.outputFiles.map((file) => [basename(file.path), file.contents]));
if (process.argv.includes('--check')) {
  const existing = new Set(await readdir(outdir));
  const missing = [...files.keys()].filter((name) => !existing.has(name)).sort();
  const unexpected = [...existing].filter((name) => !files.has(name)).sort();
  if (missing.length || unexpected.length) {
    const differences = [
      ...missing.map((name) => `Missing: ${name}`),
      ...unexpected.map((name) => `Unexpected: ${name}`),
    ];
    throw new Error(
      `UI assets differ:\n${differences.join('\n')}\nRun npm run build:ui and commit src/static/ui/`
    );
  }
  for (const [name, contents] of files) {
    if (!Buffer.from(await readFile(resolve(outdir, name))).equals(Buffer.from(contents))) {
      throw new Error(`Stale UI asset ${name}; run npm run build:ui and commit src/static/ui/`);
    }
  }
} else {
  await mkdir(outdir, { recursive: true });
  for (const name of await readdir(outdir)) {
    if (!files.has(name)) await rm(resolve(outdir, name));
  }
  for (const [name, contents] of files) await writeFile(resolve(outdir, name), contents);
}
console.log(`UI assets ${process.argv.includes('--check') ? 'verified' : 'built'} (${files.size} files)`);
