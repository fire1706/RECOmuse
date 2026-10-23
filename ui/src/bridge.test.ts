// Tests de l'attente du pont pywebview.

import { afterEach, describe, expect, it, vi } from 'vitest'

import { type PythonApi, waitForBridge } from './bridge'

const fakeApi = { ping: async () => 'pong' } as PythonApi

describe('waitForBridge', () => {
  afterEach(() => {
    delete window.pywebview
    vi.useRealTimers()
  })

  it('renvoie le pont immédiatement s’il est déjà prêt', async () => {
    window.pywebview = { api: fakeApi }
    await expect(waitForBridge()).resolves.toBe(fakeApi)
  })

  it('attend l’événement « pywebviewready »', async () => {
    const pending = waitForBridge()
    window.pywebview = { api: fakeApi }
    window.dispatchEvent(new Event('pywebviewready'))
    await expect(pending).resolves.toBe(fakeApi)
  })

  it('renvoie null si le pont n’arrive jamais', async () => {
    vi.useFakeTimers()
    const pending = waitForBridge(1000)
    vi.advanceTimersByTime(1000)
    await expect(pending).resolves.toBeNull()
  })
})
