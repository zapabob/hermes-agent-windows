/* global document, window, CompositionEvent, KeyboardEvent, InputEvent */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import crypto from 'node:crypto'
import path from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
const require = createRequire(import.meta.url)
const { build } = require('esbuild')
const { chromium } = require('playwright')
const app = path.resolve(import.meta.dirname, '../..')
const [out, mutant = 'none'] = process.argv.slice(2)
assert(['none', 'isComposing', 'keyCode229', 'compositionend-flush'].includes(mutant))
await fs.mkdir(out, { recursive: false })
const sha = b => crypto.createHash('sha256').update(b).digest('hex')
const composer = path.join(app, 'src/app/chat/composer/index.tsx')
const original = await fs.readFile(composer)
const receipt = { started: new Date().toISOString(), platform: process.platform, node: process.version,
 mode: 'actual production ChatBar, file URL, owned scripted RPC seam; no HTTP server or Electron launch',
 mutant, composer_before: sha(original), cases: [], errors: [], blockedRequests: [] }
const aliases = {
 '@': path.join(app, 'src'),
 react: path.dirname(require.resolve('react/package.json')),
 'react-dom': path.dirname(require.resolve('react-dom/package.json'))
}
try {
 const result = await build({ entryPoints: [path.join(import.meta.dirname, 'renderer.tsx')],
  outfile: path.join(out, 'bundle.js'), bundle: true, platform: 'browser', format: 'iife', jsx: 'automatic',
  alias: aliases, define: { 'process.env.NODE_ENV': '"test"', 'import.meta.env': '{}', 'import.meta.hot': 'false' },
  loader: { '.css': 'empty', '.woff': 'dataurl', '.woff2': 'dataurl', '.svg': 'dataurl' },
  metafile: true, plugins: mutant === 'none' ? [] : [{ name: 'owned-chatbar-mutant', setup(build) {
   build.onLoad({ filter: /app[\\/]chat[\\/]composer[\\/]index\.tsx$/ }, async ({ path: input }) => {
    assert.equal(path.resolve(input), composer)
    let contents = original.toString('utf8')
    const needle = mutant === 'compositionend-flush'
      ? 'flushEditorToDraft(event.currentTarget)\n        }}\n        onCompositionStart='
      : mutant === 'isComposing'
        ? 'if (composingRef.current || event.nativeEvent.isComposing) {'
        : "if (event.key === 'Enter' && event.keyCode === 229) {"
    assert.equal(contents.split(needle).length, 2)
    contents = contents.replace(needle, mutant === 'compositionend-flush'
      ? '/* owned mutation: omitted compositionend flush */\n        }}\n        onCompositionStart='
      : 'if (false) {')
    receipt.mutation = { needle, original_sha256: sha(original), derivative_sha256: sha(Buffer.from(contents)) }
    return { contents, loader: 'tsx' }
   })
  } }] })
 receipt.inputs = {}
 for (const relative of Object.keys(result.metafile.inputs)) {
  if (relative.startsWith('<')) { (receipt.virtualInputs ??= []).push(relative); continue }
  const absolute = path.resolve(app, relative)
  receipt.inputs[absolute] = sha(await fs.readFile(absolute))
 }
 receipt.bundle_sha256 = sha(await fs.readFile(path.join(out, 'bundle.js')))
 await fs.writeFile(path.join(out, 'index.html'), '<!doctype html><meta charset="utf-8"><title>F04c owned actual composer acceptance</title><div id="root"></div><script src="./bundle.js"></script>', 'utf8')
 const browser = await chromium.launch({ headless: true })
 receipt.browser = browser.version()
 try {
  for (const text of ['確定した日本語', '/f04c-effect 日本語の引数']) {
   const context = await browser.newContext()
   try {
    await context.route('**/*', async route => {
     if (route.request().url().startsWith('file:')) await route.continue()
     else { receipt.blockedRequests.push(route.request().url()); await route.abort() }
    })
    const page = await context.newPage()
    page.on('pageerror', error => receipt.errors.push(String(error)))
    await page.goto(pathToFileURL(path.join(out, 'index.html')).href)
    const editor = page.locator('[contenteditable="true"][role="textbox"]')
    await editor.waitFor({ state: 'attached', timeout: 15000 })
    await editor.focus()
    const event = async (type, options) => page.evaluate(({ type, options }) => {
     const input = document.querySelector('[contenteditable="true"][role="textbox"]')
     input.dispatchEvent(type.startsWith('composition') ? new CompositionEvent(type, { bubbles: true, ...options }) : new KeyboardEvent(type, { bubbles: true, cancelable: true, ...options }))
    }, { type, options })
    const snapshot = () => page.evaluate(() => structuredClone(window.f04cEffects))
    await event('compositionstart', {})
    await page.evaluate(text => {
     const input = document.querySelector('[contenteditable="true"][role="textbox"]')
     input.textContent = text
     const range = document.createRange(); range.selectNodeContents(input); range.collapse(false)
     const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range)
     input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertCompositionText', isComposing: true, data: text }))
    }, '未確定の日本語')
    await event('keydown', { key: 'Enter', keyCode: 13, isComposing: true })
    assert.deepEqual((await snapshot()).submissions, [], 'isComposing Enter dispatched')
    receipt.cases.push({ text, case: 'compositionstart/isComposing Enter negative', pass: true })
    await event('keydown', { key: 'Enter', keyCode: 229, isComposing: true })
    assert.deepEqual((await snapshot()).submissions, [], 'composing keyCode229 dispatched')
    assert.equal((await snapshot()).draftText, '', 'uncommitted text entered runtime')
    // Final DOM differs from preedit and no trailing input event repairs it.
    await editor.evaluate((input, text) => { input.textContent = text }, text)
    await event('compositionend', { data: text })
    await page.waitForFunction(text => window.f04cEffects.draftText === text, text, { timeout: 1000 }).catch(() => undefined)
    assert.equal((await snapshot()).draftText, text, 'compositionend failed to flush actual runtime before keydown')
    receipt.cases.push({ text, case: 'compositionend final DOM reaches real runtime before keydown', pass: true })
    await event('keydown', { key: 'Enter', keyCode: 229, isComposing: false })
    assert.deepEqual((await snapshot()).submissions, [], 'post-compositionend keyCode229 dispatched')
    assert.deepEqual((await snapshot()).rpc, [], 'negative IME dispatched RPC')
    receipt.cases.push({ text, case: 'keyCode229 after compositionend negative', pass: true })
    await event('keydown', { key: 'Enter', keyCode: 13, isComposing: false })
    await page.waitForFunction(() => window.f04cEffects.submissions.length === 1)
    const effects = await snapshot()
    assert.deepEqual(effects.submissions, [text])
    assert.equal(await editor.textContent(), '')
    if (text.startsWith('/')) {
     assert.deepEqual(effects.rpc, [{ method: 'slash.exec', params: { session_id: 'f04c-explicit-runtime', command: 'f04c-effect 日本語の引数' } }])
     assert.deepEqual(effects.outputs, [{ runtime: 'f04c-explicit-runtime', text: 'slash:/f04c-effect\nowned slash result 日本語', stored: 'f04c-stored' }])
    } else assert.deepEqual(effects.rpc, [])
    receipt.cases.push({ text, case: 'ordinary Enter finalized send and actual slash effect', pass: true, effects })
   } finally { await context.close() }
  }
 } finally { await browser.close() }
 assert.deepEqual(receipt.errors, [])
 receipt.pass = true
} catch (error) {
 receipt.pass = false
 receipt.failure = String(error.stack || error)
 console.error(receipt.failure)
 process.exitCode = 1
} finally {
 receipt.composer_after = sha(await fs.readFile(composer))
 receipt.source_continuity = receipt.composer_after === receipt.composer_before
 if (!receipt.source_continuity) {
  receipt.pass = false
  receipt.failure = (receipt.failure ? receipt.failure + '\n' : '') + 'Composer raw SHA changed during native run'
  process.exitCode = 1
 }
 receipt.finished = new Date().toISOString()
 await fs.writeFile(path.join(out, 'receipt.json'), JSON.stringify(receipt, null, 2) + '\n', 'utf8')
 console.log(JSON.stringify({ pass: receipt.pass, cases: receipt.cases.length, receipt: path.join(out, 'receipt.json') }))
}
