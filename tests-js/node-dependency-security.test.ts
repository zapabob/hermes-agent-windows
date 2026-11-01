import assert from 'node:assert/strict'
import fs from 'node:fs'
import http from 'node:http'
import { createRequire } from 'node:module'
import os from 'node:os'
import path from 'node:path'
import vm from 'node:vm'

import { afterEach, test } from 'vitest'

const root = path.resolve(__dirname, '..')
const rootRequire = createRequire(path.join(root, 'package.json'))
const fixtures: string[] = []

interface MatcherOptions { [key: string]: unknown }
interface CallableMatcher {
  (input: string, pattern: string, options?: MatcherOptions): boolean
  match(list: string[], pattern: string, options?: MatcherOptions): string[]
  defaults(options: MatcherOptions): CallableMatcher
  braceExpand(pattern: string, options?: MatcherOptions): string[]
  Minimatch: new (pattern: string, options?: MatcherOptions) => { match(input: string): boolean }
}
interface LegacyGlob {
  (pattern: string, options: MatcherOptions, callback: (error: Error | null, files: string[]) => void): void
  sync(pattern: string, options: MatcherOptions): string[]
}

function fixture(): string {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-node-security-'))
  fixtures.push(directory)
  fs.mkdirSync(path.join(directory, 'nested'))

  for (const name of ['main.js', 'skip.txt', '.hidden.js', 'nested/worker.js', 'nested/native.node']) {
    fs.writeFileSync(path.join(directory, name), `fixture: ${name}\n`, 'utf8')
  }

  return directory
}

afterEach(() => {
  for (const directory of fixtures.splice(0)) {
    assert.ok(path.resolve(directory).startsWith(path.join(os.tmpdir(), 'hermes-node-security-')))
    fs.rmSync(directory, { recursive: true, force: true })
  }
})

test('committed matcher archive contains exactly the reviewed source files', async () => {
  const directory = fixture()
  const source = path.join(root, 'website/vendor/minimatch-compat')
  const archive = path.join(root, 'website/vendor/hermes-agent-minimatch-compat-1.0.0.tgz')
  const tar = rootRequire('tar') as { x(options: MatcherOptions): Promise<void> }
  await tar.x({ file: archive, cwd: directory, strict: true })
  const extracted = path.join(directory, 'package')
  const files = fs.readdirSync(source).sort()
  assert.deepEqual(fs.readdirSync(extracted).sort(), files)

  for (const name of files) {
    assert.deepEqual(fs.readFileSync(path.join(extracted, name)), fs.readFileSync(path.join(source, name)), name)
  }
})

test('legacy callable matching retains options, defaults and upstream input validation', () => {
  const asarRequire = createRequire(rootRequire.resolve('@electron/asar'))
  const matcher = asarRequire('minimatch') as CallableMatcher
  assert.equal(matcher('nested/main.js', '**/*.{js,ts}'), true)
  assert.equal(matcher('nested/main.txt', '**/*.{js,ts}'), false)
  assert.equal(matcher('.hidden.js', '*.js'), false)
  assert.equal(matcher.defaults({ dot: true })('.hidden.js', '*.js'), true)
  assert.equal(new matcher.Minimatch('**/*.js').match('nested/main.js'), true)
  assert.deepEqual(matcher.match(['a.js', 'b.txt'], '*.js'), ['a.js'])
  assert.deepEqual(matcher.braceExpand('file.{js,ts}'), ['file.js', 'file.ts'])
  assert.throws(() => matcher('file', null as unknown as string), TypeError)
})

test('glob 7 retains synchronous and callback traversal, dotfiles, braces and ignore rules', async () => {
  const directory = fixture()
  const rimrafRequire = createRequire(rootRequire.resolve('rimraf'))
  const glob = rimrafRequire('glob') as LegacyGlob
  const options = { cwd: directory, nodir: true }
  const expected = ['main.js', 'nested/worker.js']
  assert.deepEqual(glob.sync('**/*.{js,ts}', options).sort(), expected)

  const files = await new Promise<string[]>((resolve, reject) => {
    glob('**/*.{js,ts}', options, (error, matches) => error ? reject(error) : resolve(matches))
  })

  assert.deepEqual(files.sort(), expected)
  assert.deepEqual(glob.sync('**/*.js', { ...options, dot: true }).sort(), ['.hidden.js', ...expected])
  assert.deepEqual(glob.sync('**/*.js', { ...options, ignore: 'nested/**' }), ['main.js'])
  assert.deepEqual(glob.sync('*.{missingjs,missingts}', { ...options, nonull: true }).sort(), ['*.missingjs', '*.missingts'])

  if (process.platform === 'win32') {
    assert.deepEqual(glob.sync('**/*.js', { ...options, ignore: 'nested\\**' }), ['main.js'])
  }
})

test('asar packaging preserves real unpack filters and extraction', async () => {
  const directory = fixture()
  const output = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-node-security-')), 'app.asar')
  fixtures.push(path.dirname(output))

  const asar = rootRequire('@electron/asar') as {
    createPackageWithOptions(source: string, target: string, options: MatcherOptions): Promise<void>
    extractFile(archive: string, name: string): Buffer
    statFile(archive: string, name: string): { unpacked?: boolean }
    uncacheAll(): void
  }

  try {
    await asar.createPackageWithOptions(directory, output, { unpack: '**/*.node' })
    assert.equal(asar.extractFile(output, 'main.js').toString('utf8'), 'fixture: main.js\n')
    assert.equal(asar.statFile(output, 'nested/native.node').unpacked, true)
    assert.equal(fs.existsSync(`${output}.unpacked/nested/native.node`), true)
  } finally {
    asar.uncacheAll()
  }
})

test('directory comparison and file lists retain legacy inclusion and exclusion behavior', () => {
  const left = fixture()
  const right = fixture()
  fs.writeFileSync(path.join(right, 'skip.txt'), 'different ignored content', 'utf8')

  const compare = rootRequire('dir-compare') as {
    compareSync(a: string, b: string, options: MatcherOptions): { same: boolean }
  }

  assert.equal(compare.compareSync(left, right, { compareContent: true, includeFilter: '*.js' }).same, true)
  const filelist = rootRequire('filelist') as { FileList: new (pattern: string) => { toArray(): string[] } }
  const pattern = `${path.relative(process.cwd(), left).replaceAll('\\', '/')}/**/*.js`
  const files = new filelist.FileList(pattern).toArray()
  assert.deepEqual(files.map(file => path.relative(left, file).replaceAll('\\', '/')).sort(), ['main.js', 'nested/worker.js'])
})

test('modern glob retains ordinary traversal and respects an already cancelled signal', async () => {
  const directory = fixture()
  const modernRequire = createRequire(rootRequire.resolve('cacache'))

  const modern = modernRequire('glob') as {
    glob(pattern: string, options: MatcherOptions): Promise<string[]>
  }

  assert.deepEqual((await modern.glob('**/*.js', { cwd: directory })).map(file => file.replaceAll('\\', '/')).sort(), ['main.js', 'nested/worker.js'])
  await assert.rejects(modern.glob('**/*', { cwd: directory, signal: AbortSignal.abort(new Error('fixture cancellation')) }), /fixture cancellation/)
})

test('wait-on Joi preserves multiple-email validation', { timeout: 15_000 }, () => {
  const waitRequire = createRequire(rootRequire.resolve('wait-on'))

  const joi = waitRequire('joi') as {
    string(): { email(options: MatcherOptions): { validate(input: string): { error?: Error } } }
  }

  const schema = joi.string().email({ multiple: true, tlds: { allow: false } })
  assert.equal(schema.validate('alice@example.test, bob@example.test').error, undefined)
  assert.ok(schema.validate('alice@example.test, invalid').error)
})

test('redirects retain ordinary headers and strip cross-realm custom credentials on origin changes', async () => {
  const servers: http.Server[] = []

  async function listen(server: http.Server): Promise<number> {
    servers.push(server)
    await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
    const address = server.address()
    assert.ok(address && typeof address !== 'string')

    return address.port
  }

  try {
    const destination = await listen(http.createServer((request, response) => {
      response.setHeader('content-type', 'application/json')
      response.end(JSON.stringify({ credential: request.headers['x-fixture-credential'], ordinary: request.headers['x-fixture-ordinary'] }))
    }))

    const origin = await listen(http.createServer((_request, response) => {
      response.writeHead(302, { location: `http://127.0.0.1:${destination}/target` })
      response.end()
    }))

    const axiosRequire = createRequire(rootRequire.resolve('axios'))
    const redirects = axiosRequire('follow-redirects') as { http: typeof http }
    const sensitiveHeaders: unknown = vm.runInNewContext('["x-fixture-credential"]')

    const result = await new Promise<string>((resolve, reject) => {
      redirects.http.get(`http://127.0.0.1:${origin}/redirect`, {
        headers: { 'x-fixture-credential': 'test-only', 'x-fixture-ordinary': 'preserved' },
        sensitiveHeaders,
      } as http.RequestOptions, response => {
        let body = ''
        response.setEncoding('utf8')
        response.on('data', (part: string) => { body += part })
        response.on('end', () => resolve(body))
      }).on('error', reject)
    })

    assert.deepEqual(JSON.parse(result), { ordinary: 'preserved' })
  } finally {
    await Promise.all(servers.map(server => new Promise<void>(resolve => {
      server.close(resolve)
      server.closeAllConnections()
    })))
  }
})
