// Tests de la fenêtre « Transposer », avec un faux moteur.

import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { InstrumentInfo, TranspositionReport } from './bridge'
import i18n from './i18n'
import { fakeApi } from './testFakes'
import TransposeDialog from './TransposeDialog'

const instruments: InstrumentInfo[] = [
  {
    id: 'euphonium',
    label: { fr: 'Euphonium / baryton', en: 'Euphonium / baritone' },
    variants: [
      { id: 'bb_treble', key: 'Bb', clef: 'G2', transposable: true },
      { id: 'c_bass', key: 'C', clef: 'F4', transposable: true },
    ],
  },
  {
    id: 'tuba',
    label: { fr: 'Tuba / basse', en: 'Tuba / bass' },
    variants: [{ id: 'c_bass', key: 'C', clef: 'F4', transposable: true }],
  },
  {
    id: 'percussion',
    label: { fr: 'Percussions', en: 'Percussion' },
    variants: [{ id: 'perc', key: null, clef: 'perc', transposable: false }],
  },
]

const report = (extra: Partial<TranspositionReport> = {}): TranspositionReport => ({
  interval: { steps: 8, semitones: 14 }, keys: [0], notes: 120, out_of_range: 0, suggested_octave: 0, ...extra,
})

function setup() {
  const check_transposition = vi.fn(async () => report())
  const transpose_score = vi.fn(async () => ({
    score: { score_id: 9, title: 'Marche', instrument: 'Euphonium / baryton en si♭, clé de sol', source_name: null, pages: [1], measure_count: 40 },
    report: report(),
  }))
  const set_score_instrument = vi.fn(async () => ({ instrument_id: 'euphonium', variant_id: 'bb_treble', detected: false }))
  const api = fakeApi({
    get_instruments: async () => instruments,
    get_score_instrument: async () => ({ instrument_id: 'euphonium', variant_id: 'c_bass', detected: true }),
    check_transposition,
    transpose_score,
    set_score_instrument,
  })
  const onCreated = vi.fn()
  const onClose = vi.fn()
  render(<TransposeDialog api={api} scoreId={3} onCreated={onCreated} onClose={onClose} />)
  return { check_transposition, transpose_score, set_score_instrument, onCreated, onClose }
}

describe('TransposeDialog', () => {
  beforeEach(async () => {
    await act(() => i18n.changeLanguage('fr'))
  })

  it("propose l'instrument reconnu et transpose pour un autre instrument", async () => {
    const { check_transposition, transpose_score, onCreated } = setup()
    expect(await screen.findByText(/Reconnu d'après le nom/)).toBeInTheDocument()
    const [sourceInstrument, sourceVersion] = screen.getAllByRole('combobox')
    expect(sourceInstrument).toHaveValue('euphonium')
    expect(sourceVersion).toHaveValue('c_bass')
    expect(screen.getByRole('option', { name: 'en ut, clé de fa' })).toBeInTheDocument()
    // Les percussions ne se transposent pas : elles ne sont pas proposées comme cible.
    const target = screen.getByLabelText('Nouvel instrument')
    expect(target.querySelectorAll('option')).toHaveLength(3)

    await act(async () => {
      fireEvent.change(target, { target: { value: 'euphonium' } })
    })
    expect(check_transposition).toHaveBeenLastCalledWith(3, {
      mode: 'instrument', target: { instrument: 'euphonium', variant: 'bb_treble' }, octave: 0,
    })
    expect(screen.getByText('Armure obtenue : Aucune altération.')).toBeInTheDocument()
    expect(screen.getByText("Toutes les notes tiennent dans l'étendue du nouvel instrument.")).toBeInTheDocument()

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Créer la partie transposée' }))
    })
    expect(transpose_score).toHaveBeenCalledWith(3, {
      mode: 'instrument', target: { instrument: 'euphonium', variant: 'bb_treble' }, octave: 0,
      name: 'Euphonium / baryton en si♭, clé de sol',
    })
    expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ score_id: 9 }))
  })

  it('conseille une octave quand des notes sortent de l’étendue', async () => {
    const { check_transposition } = setup()
    check_transposition.mockResolvedValue(report({ out_of_range: 30, suggested_octave: -1, keys: [-2] }))
    await screen.findByText(/Reconnu d'après le nom/)
    await act(async () => {
      fireEvent.change(screen.getByLabelText('Nouvel instrument'), { target: { value: 'tuba' } })
    })
    expect(screen.getByText(/30 notes sur 120 sortent de l'étendue/)).toHaveTextContent('Essayez : 1 octave plus bas.')
    expect(screen.getByText('Armure obtenue : 2 bémols.')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '1 octave plus bas (conseillé)' })).toBeInTheDocument()
  })

  it("transpose d'un intervalle et corrige l'instrument de la partie", async () => {
    const { check_transposition, set_score_instrument, onClose } = setup()
    await screen.findByText(/Reconnu d'après le nom/)
    await act(async () => {
      fireEvent.click(screen.getByLabelText("D'un intervalle"))
    })
    expect(check_transposition).toHaveBeenLastCalledWith(3, { mode: 'interval', interval: 'M2', direction: 'up', octave: 0 })
    await act(async () => {
      fireEvent.change(screen.getByLabelText('Sens'), { target: { value: 'down' } })
    })
    expect(check_transposition).toHaveBeenLastCalledWith(3, { mode: 'interval', interval: 'M2', direction: 'down', octave: 0 })

    await act(async () => {
      fireEvent.change(screen.getAllByRole('combobox')[1], { target: { value: 'bb_treble' } })
    })
    expect(set_score_instrument).toHaveBeenCalledWith(3, 'euphonium', 'bb_treble')
    expect(screen.queryByText(/Reconnu d'après le nom/)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Annuler' }))
    expect(onClose).toHaveBeenCalled()
  })
})
