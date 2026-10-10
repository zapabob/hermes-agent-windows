import { createServer } from 'node:net'

import { expect, it } from 'vitest'

import { assertLoopbackListenerStopped } from './owned-process-observer'

it('rejects an open listener that never sends an HTTP response, then proves refusal after close', async () => {
  const server = createServer(socket => socket.destroy())
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  if (!address || typeof address === 'string') {throw new Error('Missing fixture port')}
  const url = `http://127.0.0.1:${address.port}`
  try {
    await expect(assertLoopbackListenerStopped(url)).rejects.toThrow('still open')
  } finally {
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()))
  }
  await assertLoopbackListenerStopped(url)
})

it('refuses to inspect a non-loopback endpoint', async () => {
  await expect(assertLoopbackListenerStopped('http://example.invalid:1234')).rejects.toThrow('loopback')
})
