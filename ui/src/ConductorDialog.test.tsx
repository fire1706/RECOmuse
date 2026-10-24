// Tests de la fenêtre « Conducteur », avec un faux moteur.

import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ScoreSummary } from './bridge'
import ConductorDialog from './ConductorDialog'
import i18n from './i18n'
import { fakeApi } from './testFakes'

const summary = (id: number, instrument: string | null, extra: Partial<ScoreSummary> = {}): ScoreSummary => ({
  score_id: id, title: 'Marche', instrument, source_name: 'marche.pdf', pages: [1], measure_count: 40,
  instruments: [], derived: null, ...extra,
})

describe('ConductorDialog', () => {
  beforeEach(async () => {
    await act(() => i18n.changeLanguage('fr'))
  })

  it("extrait les parties d'un conducteur", async () => {
    const parts = [summary(5, 'Trompette 1', { derived: 'extracted' }), summary(6, 'Trombone 1', { derived: 'extracted' })]
    const extract_parts = vi.fn(async () => ({ scores: parts }))
    const onCreated = vi.fn()
    const score = summary(1, null, { instruments: ['Trompette 1', 'Trombone 1', null] })
    render(<ConductorDialog api={fakeApi({ extract_parts })} score={score} onCreated={onCreated} onClose={() => {}} />)
    expect(screen.getByText('Cette partition est un conducteur de 3 instruments :')).toBeInTheDocument()
    expect(screen.getByText('Portée 3 (sans nom)')).toBeInTheDocument()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Extraire les 3 parties' }))
    })
    expect(extract_parts).toHaveBeenCalledWith(1)
    expect(onCreated).toHaveBeenCalledWith(parts)
  })

  it('assemble un conducteur avec les parties cochées', async () => {
    const piece = [
      summary(1, 'Trompette 1'), summary(2, 'Trombone 1'),
      summary(3, 'Trompette 1', { derived: 'extracted' }),
      summary(4, null, { instruments: ['Trompette 1', 'Trombone 1'] }),
    ]
    const assembled = summary(9, null, { derived: 'assembled', pages: [], instruments: ['Trompette 1', 'Trombone 1'] })
    const assemble_conductor = vi.fn(async () => ({ score: assembled }))
    const onCreated = vi.fn()
    const api = fakeApi({ get_piece_scores: async () => piece, assemble_conductor })
    render(<ConductorDialog api={api} score={piece[0]} onCreated={onCreated} onClose={() => {}} />)
    expect(await screen.findByText(/Trompette 1 \(extraite d'un conducteur\)/)).toBeInTheDocument()
    expect(screen.getByText(/\(conducteur\)/)).toBeInTheDocument()
    // Cochées d'office : les parties lues (ni copies, ni conducteurs).
    const boxes = screen.getAllByRole('checkbox')
    expect(boxes.map((b) => (b as HTMLInputElement).checked)).toEqual([true, true, false, false])
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Assembler les 2 parties' }))
    })
    expect(assemble_conductor).toHaveBeenCalledWith([1, 2])
    expect(onCreated).toHaveBeenCalledWith([assembled])
    fireEvent.click(boxes[1])
    expect(screen.getByRole('button', { name: 'Assembler 1 partie' })).toBeDisabled()
  })

  it("dit quand le morceau n'a pas d'autres parties", async () => {
    const api = fakeApi({ get_piece_scores: async () => [summary(1, 'Flûte')] })
    render(<ConductorDialog api={api} score={summary(1, 'Flûte')} onCreated={() => {}} onClose={() => {}} />)
    expect(await screen.findByText(/Aucune autre partie de ce morceau/)).toBeInTheDocument()
  })
})
