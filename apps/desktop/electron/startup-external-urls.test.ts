import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { afterEach, test } from 'vitest'

import { configuredStartupExternalUrlsFromYaml, startupExternalUrlsConfigPath } from './startup-external-urls'

const tempRoots: string[] = []

function makeHermesHome(): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-startup-urls-'))

  tempRoots.push(root)

  return root
}

afterEach(() => {
  for (const root of tempRoots.splice(0)) {
    fs.rmSync(root, { force: true, recursive: true })
  }
})

test('public build opens no personal service when profile settings are absent', () => {
  assert.deepEqual(configuredStartupExternalUrlsFromYaml('desktop: {}'), [])
})

test('configured X and YouTube URLs are returned for the OS default browser', () => {
  assert.deepEqual(
    configuredStartupExternalUrlsFromYaml(`
desktop:
  startup_external_urls:
    x: https://x.com/home
    youtube: https://www.youtube.com/feed/subscriptions
`),
    ['https://x.com/home', 'https://www.youtube.com/feed/subscriptions']
  )
})

test('startup settings reject malformed, executable, and cross-service values', () => {
  assert.deepEqual(
    configuredStartupExternalUrlsFromYaml(`
desktop:
  startup_external_urls:
    x: javascript:alert(1)
    youtube: https://x.com/not-youtube
`),
    []
  )
})

test('startup settings reject plaintext transport and URL credentials', () => {
  assert.deepEqual(
    configuredStartupExternalUrlsFromYaml(`
desktop:
  startup_external_urls:
    x: http://x.com/home
    youtube: https://owner:secret@youtube.com/feed/subscriptions
`),
    []
  )
})

test('service subdomains and trailing-dot hosts remain valid', () => {
  assert.deepEqual(
    configuredStartupExternalUrlsFromYaml(`
desktop:
  startup_external_urls:
    x: https://mobile.twitter.com./home
    youtube: https://music.youtube.com./
`),
    ['https://mobile.twitter.com./home', 'https://music.youtube.com./']
  )
})

test('malformed YAML fails closed without delaying Desktop startup', () => {
  assert.deepEqual(configuredStartupExternalUrlsFromYaml('desktop: [not closed'), [])
})

test('config path follows the active Desktop profile', () => {
  const hermesHome = makeHermesHome()

  assert.equal(startupExternalUrlsConfigPath(hermesHome, null), path.join(hermesHome, 'config.yaml'))
  assert.equal(startupExternalUrlsConfigPath(hermesHome, 'default'), path.join(hermesHome, 'config.yaml'))
  assert.equal(
    startupExternalUrlsConfigPath(hermesHome, 'work'),
    path.join(hermesHome, 'profiles', 'work', 'config.yaml')
  )
})

test('an unset Desktop profile follows the validated sticky active profile', () => {
  const hermesHome = makeHermesHome()

  fs.writeFileSync(path.join(hermesHome, 'active_profile'), 'work\n', 'utf8')

  assert.equal(
    startupExternalUrlsConfigPath(hermesHome, null),
    path.join(hermesHome, 'profiles', 'work', 'config.yaml')
  )
})

test('an explicit Desktop profile wins over sticky profile state', () => {
  const hermesHome = makeHermesHome()

  fs.writeFileSync(path.join(hermesHome, 'active_profile'), 'work\n', 'utf8')

  assert.equal(startupExternalUrlsConfigPath(hermesHome, 'default'), path.join(hermesHome, 'config.yaml'))
  assert.equal(
    startupExternalUrlsConfigPath(hermesHome, 'personal'),
    path.join(hermesHome, 'profiles', 'personal', 'config.yaml')
  )
})

test('invalid explicit or sticky profiles cannot escape HERMES_HOME', () => {
  const hermesHome = makeHermesHome()

  fs.writeFileSync(path.join(hermesHome, 'active_profile'), '../outside\n', 'utf8')

  assert.equal(startupExternalUrlsConfigPath(hermesHome, null), path.join(hermesHome, 'config.yaml'))
  assert.equal(startupExternalUrlsConfigPath(hermesHome, '../outside'), path.join(hermesHome, 'config.yaml'))
})
