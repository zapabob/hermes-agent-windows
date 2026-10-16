'use strict';

const assert = require('node:assert/strict');
const { once } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createRequire } = require('node:module');
const { spawnSync } = require('node:child_process');
const test = require('node:test');
const forkRoot = path.resolve(__dirname, '../vendor/braces-iterative');
const braces = require(forkRoot);

test('compile and expansion retain document globs, ranges, Unicode and options', () => {
  assert.equal(braces.compile('docs/{guide,reference}/**/*.{md,mdx}'), 'docs/(guide|reference)/**/*.(md|mdx)');
  assert.deepEqual(braces.expand('文書/{01..05..2}/{導入,参照}'), [
    '文書/01/導入', '文書/01/参照', '文書/03/導入', '文書/03/参照', '文書/05/導入', '文書/05/参照'
  ]);
  assert.deepEqual(braces.expand('{a,a,,文書}', { nodupes: true, noempty: true }), ['a', '文書']);
  assert.deepEqual(braces.expand('{5..1..2}'), ['5', '3', '1']);
  assert.deepEqual(braces.expand('${a,b}'), ['${a,b}']);
  assert.deepEqual(braces.expand('\\{a,b}'), ['{a,b}']);
  assert.throws(() => braces.expand('{1..20}', { rangeLimit: 2 }), RangeError);
  assert.equal(braces.stringify(braces.parse('docs/{a,{b,c}}/*.md')), 'docs/{a,{b,c}}/*.md');
});

test('each locked braces consumer resolves the actual maintained source', () => {
  const lock = require('../package-lock.json');
  const entries = Object.entries(lock.packages);
  const expected = fs.realpathSync(path.join(forkRoot, 'index.js'));
  let consumers = 0;
  for (const [relative, metadata] of entries) {
    if (!metadata.dependencies?.braces) continue;
    const importer = path.resolve(__dirname, '..', relative || '.');
    const loaded = require.resolve('braces', { paths: [importer] });
    assert.equal(fs.realpathSync(loaded), expected, `${relative || 'website'} must use the patched implementation`);
    consumers++;
  }
  assert.ok(consumers > 0, 'Exercise the real dependency graph');
  for (const [relative, metadata] of entries) {
    if (relative === 'node_modules/braces' || relative.endsWith('/node_modules/braces')) {
      assert.equal(metadata.link, true, `${relative} must resolve to the local source fork`);
      assert.ok(lock.packages[metadata.resolved]?.name === '@hermes-agent/braces-iterative', 'No broken or registry braces fallback');
    }
  }
});

test('Docusaurus file enumeration and micromatch retain nested brace patterns', async () => {
  const utilsRequire = createRequire(require.resolve('@docusaurus/utils/package.json'));
  const globby = utilsRequire('globby');
  const micromatch = utilsRequire('micromatch');
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-braces-glob-'));
  fs.mkdirSync(path.join(fixture, 'guide'));
  for (const name of ['guide/intro.md', 'guide/details.mdx', 'guide/skip.txt']) {
    fs.writeFileSync(path.join(fixture, name), 'owned qualification fixture\n');
  }
  assert.deepEqual((await globby(['**/*.{md,mdx}'], { cwd: fixture })).sort(), ['guide/details.mdx', 'guide/intro.md']);
  assert.equal(micromatch.isMatch('guide/intro.md', '**/*.{md,mdx}'), true);
  assert.equal(micromatch.isMatch('guide/skip.txt', '**/*.{md,mdx}'), false);
  assert.deepEqual(micromatch.braces('{01..03}', { expand: true, nodupes: true, keepEscaping: true }), ['01', '02', '03']);
});

test('Chokidar detects a new matching document after ready', { timeout: 15000 }, async t => {
  const coreRequire = createRequire(require.resolve('@docusaurus/core/package.json'));
  const chokidar = coreRequire('chokidar');
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-braces-watch-'));
  const glob = fixture.replaceAll('\\', '/') + '/**/*.{md,mdx}';
  const watcher = chokidar.watch(glob, { ignoreInitial: true });
  t.after(() => watcher.close());
  await once(watcher, 'ready');
  const added = once(watcher, 'add');
  fs.mkdirSync(path.join(fixture, 'created-after-ready'));
  const document = path.join(fixture, 'created-after-ready/new.mdx');
  fs.writeFileSync(document, '# Owned fixture\n');
  const [actual] = await added;
  assert.equal(path.resolve(actual), document);
});

for (const operation of ['parse', 'compile', 'expand', 'stringify']) {
  test(`${operation} traverses deep valid input with a bounded native stack`, () => {
    const code = `const assert=require('node:assert/strict');const b=require(${JSON.stringify(forkRoot)});const p='{'.repeat(4500)+'x'+'}'.repeat(4500);const op=${JSON.stringify(operation)};if(op==='parse'){b.parse('{1..'+p+',b}');}else{assert.deepEqual(b[op](p),op==='expand'?[p]:p);}`;
    const child = spawnSync(process.execPath, ['--stack_size=256', '--max-old-space-size=192', '-e', code], {
      encoding: 'utf8', windowsHide: true, timeout: 15000
    });
    assert.equal(child.error, undefined);
    assert.equal(child.status, 0, child.stderr);
  });
}
