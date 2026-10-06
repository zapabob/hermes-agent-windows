import { safeBackgroundImageFit, safeBackgroundImagePosition, safeBackgroundOverlay } from '@hermes/shared/skin-css'
import { useStore } from '@nanostores/react'
import { Leva, useControls } from 'leva'
import { type CSSProperties, useEffect, useMemo, useState } from 'react'

import { isFileMediaPath, isNetworkFilePath, resolveMediaDisplaySrc } from '@/lib/media'
import { $backdrop } from '@/store/backdrop'
import { useTheme } from '@/themes/context'

const BLEND_MODES = [
  'normal',
  'multiply',
  'screen',
  'overlay',
  'darken',
  'lighten',
  'color-dodge',
  'color-burn',
  'hard-light',
  'soft-light',
  'difference',
  'exclusion',
  'hue',
  'saturation',
  'color',
  'luminosity'
] as const

type BlendMode = (typeof BLEND_MODES)[number]
const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`

export function Backdrop() {
  const [controlsOpen, setControlsOpen] = useState(false)
  const [skinWallpaperUrl, setSkinWallpaperUrl] = useState<string | null>(null)
  const on = useStore($backdrop)
  const { theme } = useTheme()
  // Use only the skin-provided wallpaper. A hardcoded local fallback causes
  // palette/wallpaper mismatch (e.g. light palette over portrait background).
  const wallpaper = (theme.backgroundImage ?? '').trim()
  // Skin YAML is user-imported: allow-list the overlay before it reaches an
  // inline style so a skin cannot smuggle url() past the media path check.
  const wallpaperOverlay = safeBackgroundOverlay(theme.backgroundOverlay)

  useEffect(() => {
    if (!import.meta.env.DEV) {
      return
    }

    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null

      const editing =
        target?.isContentEditable ||
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement

      if (editing || event.repeat || event.altKey || event.ctrlKey || event.metaKey) {
        return
      }

      if (event.shiftKey && event.code === 'KeyY') {
        setControlsOpen((open: boolean) => !open)
      }
    }

    window.addEventListener('keydown', onKeyDown)

    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  // Resolve skin wallpaper 竊・data URL via Electron when needed.
  useEffect(() => {
    let cancelled = false

    if (!wallpaper) {
      setSkinWallpaperUrl(null)

      return
    }

    // A backend skin may be remote. Keep the renderer from making arbitrary
    // outbound requests: public HTTP(S) images go through the main-process
    // SSRF-safe bridge, files use the authenticated media path, and inline
    // data must identify itself as an image. UNC paths are never accepted.
    if (/^https?:\/\//i.test(wallpaper)) {
      if (!window.hermesDesktop?.readImageDataUrl) {
        setSkinWallpaperUrl(null)

        return
      }

      void window.hermesDesktop
        .readImageDataUrl(wallpaper)
        .then(src => {
          if (!cancelled) {
            setSkinWallpaperUrl(src || null)
          }
        })
        .catch(() => {
          if (!cancelled) {
            setSkinWallpaperUrl(null)
          }
        })

      return () => {
        cancelled = true
      }
    }

    if (isNetworkFilePath(wallpaper) || (!isFileMediaPath(wallpaper) && !/^data:image\//i.test(wallpaper))) {
      setSkinWallpaperUrl(null)

      return
    }

    void resolveMediaDisplaySrc(wallpaper, theme.backgroundImageSource)
      .then(src => {
        if (!cancelled) {
          setSkinWallpaperUrl(src || null)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSkinWallpaperUrl(null)
        }
      })

    return () => {
      cancelled = true
    }
  }, [theme.backgroundImageSource, wallpaper])

  const shape = useControls(
    'UI / Shape',
    { radiusScalar: { value: 0.2, min: 0, max: 2, step: 0.1, label: 'radius scalar' } },
    { collapsed: true }
  )

  useEffect(() => {
    document.documentElement.style.setProperty('--radius-scalar', String(shape.radiusScalar))
  }, [shape.radiusScalar])

  const statue = useControls(
    'Backdrop / Statue',
    {
      enabled: { value: true, label: 'on' },
      opacity: { value: 0.025, min: 0, max: 1, step: 0.005 },
      blendMode: { value: 'difference' as BlendMode, options: BLEND_MODES, label: 'blend' },
      invert: { value: true, label: 'invert color' },
      saturate: { value: 1, min: 0, max: 3, step: 0.05, label: 'saturate' },
      brightness: { value: 1, min: 0, max: 2, step: 0.05, label: 'brightness' },
      objectPosition: {
        value: 'top left',
        options: ['top left', 'top right', 'bottom left', 'bottom right', 'center', 'top', 'bottom', 'left', 'right'],
        label: 'position'
      },
      scale: { value: 160, min: 100, max: 300, step: 5, label: 'height (dvh)' }
    },
    { collapsed: true }
  )

  const skinFit = safeBackgroundImageFit(theme.backgroundImageFit)
  const skinPosition = safeBackgroundImagePosition(theme.backgroundImagePosition)
  // When a wallpaper is active, the chat surface must be opaque so text stays
  // readable over the image. We signal this via a CSS class on <html>.
  const hasWallpaper = !!skinWallpaperUrl

  useEffect(() => {
    document.documentElement.classList.toggle('has-skin-wallpaper', hasWallpaper)

    return () => document.documentElement.classList.remove('has-skin-wallpaper')
  }, [hasWallpaper])

  const skinOverlay = wallpaperOverlay

  const skinLayer = useMemo(() => {
    if (!skinWallpaperUrl) {
      return null
    }

    return (
      <div aria-hidden className="pointer-events-none absolute inset-0 z-0 overflow-hidden" data-hermes-skin-wallpaper>
        <img
          alt=""
          className="h-full w-full"
          fetchPriority="low"
          src={skinWallpaperUrl}
          style={{
            objectFit: skinFit as CSSProperties['objectFit'],
            objectPosition: skinPosition
          }}
        />
        {skinOverlay ? (
          <div className="absolute inset-0" data-hermes-skin-wallpaper-overlay style={{ background: skinOverlay }} />
        ) : null}
      </div>
    )
  }, [skinFit, skinOverlay, skinPosition, skinWallpaperUrl])

  return (
    <>
      <Leva collapsed hidden={!import.meta.env.DEV || !controlsOpen} titleBar={{ title: 'backdrop', drag: true }} />

      {skinLayer}

      {on && statue.enabled && !skinWallpaperUrl && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 z-2"
          style={{
            mixBlendMode: statue.blendMode as CSSProperties['mixBlendMode'],
            opacity: statue.opacity
          }}
        >
          <img
            alt=""
            className="w-auto min-w-dvw object-cover"
            fetchPriority="low"
            src={assetPath('ds-assets/filler-bg0.jpg')}
            style={{
              height: `${statue.scale}dvh`,
              objectPosition: statue.objectPosition,
              filter: `invert(calc(${statue.invert ? 1 : 0} * var(--backdrop-invert-mul, 1))) saturate(${statue.saturate}) brightness(${statue.brightness})`
            }}
          />
        </div>
      )}
    </>
  )
}
