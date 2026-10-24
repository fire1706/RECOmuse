// Tests de la barre de progression de la lecture.

import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ReadingState } from './bridge'
import ReadingProgress, { remainingSeconds } from './ReadingProgress'
import i18n from './i18n'

const state = (over: Partial<ReadingState> = {}): ReadingState => ({
  stage: 'audiveris',
  page: 3,
  pages: 12,
  fraction: 0.25,
  elapsed: 120,
  cancelling: false,
  ...over,
})

describe('remainingSeconds', () => {
  it('prolonge le rythme déjà pris', () => {
    // Un quart fait en 2 minutes : il en reste 6.
    expect(remainingSeconds(0.25, 120)).toBe(360)
  })

  it("ne devine pas trop tôt", () => {
    expect(remainingSeconds(0.01, 120)).toBeNull()
    expect(remainingSeconds(0.5, 3)).toBeNull()
    expect(remainingSeconds(1, 120)).toBeNull()
  })
})

describe('ReadingProgress', () => {
  beforeEach(async () => {
    await act(() => i18n.changeLanguage('fr'))
  })

  it("montre l'étape, la page, le pourcentage et le temps restant", () => {
    render(<ReadingProgress state={state()} onCancel={() => {}} />)
    expect(screen.getByText(/Reconnaissance de la musique/)).toBeInTheDocument()
    expect(screen.getByText(/page 3 sur 12/)).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '25')
    expect(screen.getByText('25 % · environ 6 minutes restantes')).toBeInTheDocument()
  })

  it('annonce moins d’une minute, ou un calcul en cours au début', () => {
    const { rerender } = render(<ReadingProgress state={state({ fraction: 0.9 })} onCancel={() => {}} />)
    expect(screen.getByText(/moins d'une minute restante/)).toBeInTheDocument()
    rerender(<ReadingProgress state={state({ fraction: 0, elapsed: 1 })} onCancel={() => {}} />)
    expect(screen.getByText(/calcul du temps restant/)).toBeInTheDocument()
  })

  it('le bouton Annuler demande l’arrêt, puis se désactive', () => {
    const onCancel = vi.fn()
    const { rerender } = render(<ReadingProgress state={state()} onCancel={onCancel} />)
    fireEvent.click(screen.getByRole('button', { name: 'Annuler' }))
    expect(onCancel).toHaveBeenCalledOnce()
    rerender(<ReadingProgress state={state({ cancelling: true })} onCancel={onCancel} />)
    expect(screen.getByRole('button', { name: 'Annuler' })).toBeDisabled()
    expect(screen.getByText(/arrêt en cours/)).toBeInTheDocument()
  })
})
