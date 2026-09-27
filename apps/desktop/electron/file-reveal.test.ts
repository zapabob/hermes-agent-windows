import assert from 'node:assert/strict'
import fs from 'node:fs'

import { test } from 'vitest'

import { createFileReveal } from './file-reveal'

test('file URL open path reveals the validated file without invoking an OS association', () => {
  const source = fs.readFileSync(new URL('./main.ts', import.meta.url), 'utf8')
  const start = source.indexOf("if (parsed.protocol === 'file:') {")
  const end = source.indexOf("if (!['http:', 'https:', 'mailto:'].includes(parsed.protocol))", start)

  assert.ok(start >= 0 && end > start)
  const fileBranch = source.slice(start, end)
  assert.match(fileBranch, /resolveRequestedPathForIpc\(/)
  assert.match(fileBranch, /revealLocalFile\(localPath\)/)
  assert.doesNotMatch(fileBranch, /shell\.openPath\(/)
})

test('reveal deduplicates repeated paths but permits a later request', () => {
  let now = 10_000
  const shown: string[] = []

  const reveal = createFileReveal({
    now: () => now,
    reveal: path => shown.push(path),
    log: () => undefined
  })

  reveal('C:/artifact/archive.tar.gz')
  reveal('C:/artifact/archive.tar.gz')
  reveal('C:/artifact/other.tar.gz')
  now += 1_500
  reveal('C:/artifact/archive.tar.gz')

  assert.deepEqual(shown, [
    'C:/artifact/archive.tar.gz',
    'C:/artifact/other.tar.gz',
    'C:/artifact/archive.tar.gz'
  ])
})

test('a failed reveal can be retried without opening the file', () => {
  const shown: string[] = []
  const logged: string[] = []

  const reveal = createFileReveal({
    now: () => 10_000,
    reveal: path => {
      shown.push(path)

      if (shown.length === 1) {
        throw new Error('file manager unavailable')
      }
    },
    log: message => logged.push(message)
  })

  reveal('C:/artifact/archive.tar.gz')
  reveal('C:/artifact/archive.tar.gz')

  assert.equal(shown.length, 2)
  assert.equal(logged.length, 1)
})
