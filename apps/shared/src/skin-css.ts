/**
 * Allow-list validation for skin-supplied CSS values.
 *
 * Skin YAML files are user-importable, so any string that reaches a React
 * inline style is untrusted input. `background` and `object-position` accept
 * CSS functions that perform outbound requests (`url()`, `image-set()`), which
 * would turn the renderer into a beacon for any imported skin. Only plain
 * colour literals are accepted for the overlay; only bounded keyword/length
 * tokens are accepted for the position; and `object-fit` is restricted to a
 * fixed literal set.
 */

/** `object-fit` literals the renderer is allowed to pass through. */
const FIT_VALUES = ['contain', 'cover', 'fill', 'none', 'scale-down'] as const

type SkinCssObjectFit = (typeof FIT_VALUES)[number]

/** Upper bound for a validated `object-position` value. */
const MAX_POSITION_LENGTH = 64

const HEX_COLOUR_RE = /^#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i

/**
 * `rgb()`/`rgba()`/`hsl()`/`hsla()` with plain numeric or percentage
 * arguments. Comma-separated and whitespace-separated channel forms are
 * accepted; unsupported functions and extra tokens are not.
 */
const COLOUR_FUNCTION_RE =
  /^(?:rgba?|hsla?)\(\s*[0-9.]+%?(?:\s*[, ]\s*[0-9.]+%?){1,3}\s*\)$/i

/**
 * `object-position` keywords plus bounded token forms. Anything carrying a
 * bracket, quote, backslash, comma or statement terminator fails to match.
 */
const POSITION_RE =
  /^(?:(?:left|right|top|bottom|center)|[-+]?[0-9.]+%?)(?:\s+(?:(?:left|right|top|bottom|center)|[-+]?[0-9.]+%?)){0,1}$/i

function normalise(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

/**
 * Return the overlay colour when `value` is a plain CSS colour literal,
 * otherwise an empty string so the caller skips the overlay entirely.
 */
export function safeBackgroundOverlay(value: unknown): string {
  const colour = normalise(value)

  if (!colour) {
    return ''
  }

  return HEX_COLOUR_RE.test(colour) || COLOUR_FUNCTION_RE.test(colour) ? colour : ''
}

/** Return a validated `object-position`, falling back to `'center'`. */
export function safeBackgroundImagePosition(value: unknown): string {
  const position = normalise(value)

  if (!position || position.length > MAX_POSITION_LENGTH) {
    return 'center'
  }

  return POSITION_RE.test(position) ? position : 'center'
}

/** Return a validated `object-fit`, falling back to `'cover'`. */
export function safeBackgroundImageFit(value: unknown): SkinCssObjectFit {
  const fit = normalise(value).toLowerCase()

  return (FIT_VALUES as readonly string[]).includes(fit) ? (fit as SkinCssObjectFit) : 'cover'
}
