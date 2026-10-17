import { describe, expect, it, vi } from 'vitest'

import { findSlashCommand } from '../app/slash/registry.js'
import type { SlashRunCtx } from '../app/slash/types.js'

describe('steer shorthand', () => {
  it('uses the local steer handler when the catalog is unavailable', () => {
    expect(findSlashCommand('s')).toBe(findSlashCommand('steer'))
    expect(findSlashCommand('S')).toBe(findSlashCommand('steer'))
  })

  it.each([false, true])('retains the existing busy=%s effect', async busy => {
    const enqueue = vi.fn()
    const rpc = vi.fn().mockResolvedValue({ status: 'queued' })

    const ctx = {
      sid: 'F03-owned',
      ui: { busy },
      composer: { enqueue },
      gateway: { rpc },
      transcript: { sys: vi.fn() },
      guarded: (callback: (result: unknown) => void) => callback,
      guardedErr: vi.fn()
    } as unknown as SlashRunCtx

    const command = findSlashCommand('s')
    expect(command).toBeDefined()
    command!.run(' Keep Case 日本語 ', ctx, 's')
    await Promise.resolve()

    if (busy) {
      expect(rpc).toHaveBeenCalledWith('session.steer', {
        session_id: 'F03-owned',
        text: 'Keep Case 日本語'
      })
      expect(enqueue).not.toHaveBeenCalled()
    } else {
      expect(enqueue).toHaveBeenCalledWith('Keep Case 日本語')
      expect(rpc).not.toHaveBeenCalled()
    }
  })
})
