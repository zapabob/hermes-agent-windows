import { safeBackgroundImageFit, safeBackgroundImagePosition, safeBackgroundOverlay } from '@hermes/shared/skin-css'
import { expect, test } from 'vitest'

test('safeBackgroundOverlay accepts plain CSS colour literals', () => {
  expect(safeBackgroundOverlay('#abc')).toBe('#abc')
  expect(safeBackgroundOverlay('#abcd')).toBe('#abcd')
  expect(safeBackgroundOverlay('#a1b2c3')).toBe('#a1b2c3')
  expect(safeBackgroundOverlay('#a1b2c3d4')).toBe('#a1b2c3d4')
  expect(safeBackgroundOverlay('rgb(0, 0, 0)')).toBe('rgb(0, 0, 0)')
  expect(safeBackgroundOverlay('rgba(0,0,0,0.5)')).toBe('rgba(0,0,0,0.5)')
  expect(safeBackgroundOverlay('hsl(210 50% 40%)')).toBe('hsl(210 50% 40%)')
  expect(safeBackgroundOverlay('hsla(210, 50%, 40%, 0.5)')).toBe('hsla(210, 50%, 40%, 0.5)')
})

test('safeBackgroundOverlay is case-insensitive and trims surrounding whitespace', () => {
  expect(safeBackgroundOverlay('  #A1B2C3  ')).toBe('#A1B2C3')
  expect(safeBackgroundOverlay('RGB(1,2,3)')).toBe('RGB(1,2,3)')
  expect(safeBackgroundOverlay('HSL(1,2%,3%)')).toBe('HSL(1,2%,3%)')
})

test('safeBackgroundOverlay rejects url() so a skin cannot beacon the renderer', () => {
  expect(safeBackgroundOverlay('url(https://evil.example/pixel.png)')).toBe('')
  expect(safeBackgroundOverlay('url(//evil.example/pixel.png)')).toBe('')
  expect(safeBackgroundOverlay('url(data:image/png;base64,AAAA)')).toBe('')
  expect(safeBackgroundOverlay('#000 url(https://evil.example/x)')).toBe('')
})

test('safeBackgroundOverlay rejects other request-capable and script CSS functions', () => {
  expect(safeBackgroundOverlay('image-set("a.png" 1x)')).toBe('')
  expect(safeBackgroundOverlay('expression(alert(1))')).toBe('')
  expect(safeBackgroundOverlay('var(--x)')).toBe('')
  expect(safeBackgroundOverlay('linear-gradient(red, blue)')).toBe('')
  expect(safeBackgroundOverlay('element(#id)')).toBe('')
  expect(safeBackgroundOverlay('paint(foo)')).toBe('')
})

test('safeBackgroundOverlay rejects statement and comment injection', () => {
  expect(safeBackgroundOverlay('#000; background: url(https://evil.example/x)')).toBe('')
  expect(safeBackgroundOverlay('#000\nurl(https://evil.example/x)')).toBe('')
  expect(safeBackgroundOverlay('/* c */ #000')).toBe('')
  expect(safeBackgroundOverlay('rgb(0,0,0)/*')).toBe('')
  expect(safeBackgroundOverlay('\\75 rl(https://evil.example/x)')).toBe('')
})

test('safeBackgroundOverlay returns an empty string for empty or non-string input', () => {
  expect(safeBackgroundOverlay('')).toBe('')
  expect(safeBackgroundOverlay('   ')).toBe('')
  expect(safeBackgroundOverlay(undefined)).toBe('')
  expect(safeBackgroundOverlay(null)).toBe('')
  expect(safeBackgroundOverlay(42)).toBe('')
})

test('safeBackgroundImagePosition accepts keywords and bounded token forms', () => {
  expect(safeBackgroundImagePosition('center')).toBe('center')
  expect(safeBackgroundImagePosition('left top')).toBe('left top')
  expect(safeBackgroundImagePosition('right bottom')).toBe('right bottom')
  expect(safeBackgroundImagePosition('50% 50%')).toBe('50% 50%')
  expect(safeBackgroundImagePosition('top center')).toBe('top center')
  expect(safeBackgroundImagePosition('  center  ')).toBe('center')
})

test('safeBackgroundImagePosition rejects url() and other CSS payloads', () => {
  expect(safeBackgroundImagePosition('url(https://evil.example/x)')).toBe('center')
  expect(safeBackgroundImagePosition('center; background: url(https://evil.example/x)')).toBe('center')
  expect(safeBackgroundImagePosition('calc(100% - 10px)')).toBe('center')
  expect(safeBackgroundImagePosition('"center"')).toBe('center')
  expect(safeBackgroundImagePosition('center\nurl(https://evil.example/x)')).toBe('center')
  expect(safeBackgroundImagePosition(`center ${'x'.repeat(80)}`)).toBe('center')
})

test('safeBackgroundImagePosition falls back for empty or non-string input', () => {
  expect(safeBackgroundImagePosition('')).toBe('center')
  expect(safeBackgroundImagePosition(undefined)).toBe('center')
  expect(safeBackgroundImagePosition(null)).toBe('center')
  expect(safeBackgroundImagePosition({})).toBe('center')
})

test('safeBackgroundImageFit accepts only the fixed literal set', () => {
  for (const fit of ['contain', 'cover', 'fill', 'none', 'scale-down']) {
    expect(safeBackgroundImageFit(fit)).toBe(fit)
  }

  expect(safeBackgroundImageFit('COVER')).toBe('cover')
  expect(safeBackgroundImageFit('  cover  ')).toBe('cover')
})

test('safeBackgroundImageFit falls back to cover for anything else', () => {
  expect(safeBackgroundImageFit('inherit')).toBe('cover')
  expect(safeBackgroundImageFit('unset')).toBe('cover')
  expect(safeBackgroundImageFit('url(https://evil.example/x)')).toBe('cover')
  expect(safeBackgroundImageFit('')).toBe('cover')
  expect(safeBackgroundImageFit(undefined)).toBe('cover')
  expect(safeBackgroundImageFit(null)).toBe('cover')
  expect(safeBackgroundImageFit(7)).toBe('cover')
})
