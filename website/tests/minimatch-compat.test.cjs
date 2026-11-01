'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const { createRequire } = require('node:module');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

test('standalone website supports callable and named matcher entry points', async () => {
  const consumer = createRequire(require.resolve('serve-handler'));
  const matcher = consumer('minimatch');
  assert.equal(typeof matcher, 'function');
  assert.equal(matcher('/docs/guide.html', '/docs/**/*.html'), true);
  assert.equal(matcher('/docs/guide.txt', '/docs/**/*.html'), false);
  const modern = await import('minimatch');
  assert.equal(modern.minimatch('/docs/guide.html', '/docs/**/*.html'), true);
  assert.equal(new modern.Minimatch('/docs/**/*.html').match('/docs/guide.html'), true);
  assert.throws(() => matcher('file', null), TypeError);
});

test('static website serving retains headers and rewrite matching', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-website-matcher-'));
  fs.mkdirSync(path.join(directory, 'assets'));
  fs.writeFileSync(path.join(directory, 'index.html'), '<main>website fixture</main>', 'utf8');
  fs.writeFileSync(path.join(directory, 'assets/readme.txt'), 'static fixture', 'utf8');
  const handler = require('serve-handler');
  const server = http.createServer((request, response) => handler(request, response, {
    public: directory,
    rewrites: [{ source: '/docs/**', destination: '/index.html' }],
    headers: [{ source: '/assets/**/*.txt', headers: [{ key: 'x-fixture-header', value: 'preserved' }] }],
  }));
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const origin = `http://127.0.0.1:${server.address().port}`;
    const staticResponse = await fetch(`${origin}/assets/readme.txt`);
    assert.equal(staticResponse.status, 200);
    assert.equal(staticResponse.headers.get('x-fixture-header'), 'preserved');
    assert.equal(await staticResponse.text(), 'static fixture');
    const rewritten = await fetch(`${origin}/docs/guide`);
    assert.equal(rewritten.status, 200);
    assert.equal(await rewritten.text(), '<main>website fixture</main>');
  } finally {
    await new Promise(resolve => { server.close(resolve); server.closeAllConnections(); });
    assert.ok(path.resolve(directory).startsWith(path.join(os.tmpdir(), 'hermes-website-matcher-')));
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test('Docusaurus Joi keeps its existing major and multiple-email validation', () => {
  const consumer = createRequire(require.resolve('@docusaurus/utils-validation'));
  const joi = consumer('joi');
  const schema = joi.string().email({ multiple: true, tlds: { allow: false } });
  assert.equal(schema.validate('alice@example.test, bob@example.test').error, undefined);
  assert.ok(schema.validate('alice@example.test, invalid').error);
});
