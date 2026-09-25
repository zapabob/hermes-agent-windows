import { createHash } from 'node:crypto'

const HEX64 = /^[a-f0-9]{64}$/

export const isHex64 = (value: unknown): value is string => typeof value === 'string' && HEX64.test(value)

// Python's sort_keys orders by code point; UTF-16 code-unit order differs for
// astral characters, so compare code points explicitly.
function compareCodePoints(a: string, b: string): number {
  const left = Array.from(a)
  const right = Array.from(b)

  for (let index = 0; index < Math.min(left.length, right.length); index += 1) {
    const delta = left[index]!.codePointAt(0)! - right[index]!.codePointAt(0)!

    if (delta !== 0) {
      return delta
    }
  }

  return left.length - right.length
}

function encode(value: unknown, depth: number): null | string {
  if (depth > 32) {
    return null
  }

  if (value === null || typeof value === 'boolean' || typeof value === 'string') {
    return JSON.stringify(value)
  }

  // Floats serialise differently in Python and JS, so only safe integers are canonical.
  if (typeof value === 'number') {
    return Number.isSafeInteger(value) ? String(value) : null
  }

  if (Array.isArray(value)) {
    const items = value.map(item => encode(item, depth + 1))

    return items.includes(null) ? null : `[${items.join(',')}]`
  }

  if (typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype) {
    const record = value as Record<string, unknown>
    const parts: string[] = []

    for (const key of Object.keys(record).sort(compareCodePoints)) {
      const encoded = encode(record[key], depth + 1)

      if (encoded === null) {
        return null
      }

      parts.push(`${JSON.stringify(key)}:${encoded}`)
    }

    return `{${parts.join(',')}}`
  }

  return null
}

/** Byte-identical to the host's canonical_json for the presentation domain. */
export function canonicalPresentationJson(presentation: unknown): null | string {
  if (!presentation || typeof presentation !== 'object' || Array.isArray(presentation)) {
    return null
  }

  return encode(presentation, 0)
}

/** SHA-256 of exactly what the approval prompt renders; null when it cannot be derived. */
export function renderedPresentationDigest(presentation: unknown): null | string {
  const canonical = canonicalPresentationJson(presentation)

  return canonical === null ? null : createHash('sha256').update(canonical, 'utf8').digest('hex')
}
