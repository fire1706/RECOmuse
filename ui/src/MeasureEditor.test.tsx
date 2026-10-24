// Tests de l'éditeur de mesure, avec un faux moteur.

import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { MeasureDetails } from './bridge'
import i18n from './i18n'
import MeasureEditor, { symbolLabel } from './MeasureEditor'
import { fakeApi } from './testFakes'

const details: MeasureDetails = {
  id: 'm12',
  number: 12,
  page: 2,
  length: 1,
  part_id: 'P1',
  duration: '3',
  expected: '4',
  attributes: [],
  events: [
    { id: 'n1', kind: 'note', value: { step: 'B', octave: 4, alter: -1, written: '1', dots: 0 }, confidence: 1, source: 'vector' },
    { id: 'n2', kind: 'note', value: { step: 'C', octave: 5, alter: 0, written: '1/2', dots: 1 }, confidence: 0.4, source: 'audiveris' },
    { id: 'r1', kind: 'rest', value: { written: '1/2', dots: 0 }, confidence: 1, source: 'vector' },
  ],
  state: { clef: { sign: 'G', line: 2 }, fifths: -1, time: '4/4' },
  previous: 'm11',
  next: 'm13',
  can_undo: true,
}

/** Clic sur un bouton, en attendant la réponse du (faux) moteur. */
const click = (name: string) =>
  act(async () => {
    fireEvent.click(screen.getByRole('button', { name }))
  })

function setup(symbolId: string | null = null) {
  const edit_score = vi.fn(async () => ({ measure_id: 'm12', symbol_id: 'n1', corrections: [7] }))
  const undo_edit = vi.fn(async () => ({ measure_id: 'm12' }))
  const api = fakeApi({ get_measure: async () => details, edit_score, undo_edit })
  const handlers = { onSelectSymbol: vi.fn(), onSelectMeasure: vi.fn(), onEdited: vi.fn() }
  render(<MeasureEditor api={api} scoreId={4} measureId="m12" symbolId={symbolId} version={0} {...handlers} />)
  return { edit_score, undo_edit, ...handlers }
}

describe('MeasureEditor', () => {
  beforeEach(async () => {
    await act(() => i18n.changeLanguage('fr'))
  })

  it('montre la mesure, ses réglages et ses symboles', async () => {
    const { onSelectSymbol, onSelectMeasure } = setup()
    expect(await screen.findByText('Mesure 12')).toBeInTheDocument()
    expect(screen.getByText('Cette mesure compte 3 noire(s) au lieu de 4.')).toBeInTheDocument()
    expect(screen.getByLabelText('Armure')).toHaveValue('-1')
    expect(screen.getByLabelText('Clé')).toHaveValue('G:2:0')
    expect(screen.getByLabelText('Nombre de temps')).toHaveValue(4)
    fireEvent.click(screen.getByRole('button', { name: 'do5, croche pointée' }))
    expect(onSelectSymbol).toHaveBeenCalledWith('n2')
    expect(screen.getByRole('button', { name: 'silence, croche' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Suivante ▶' }))
    expect(onSelectMeasure).toHaveBeenCalledWith('m13')
  })

  it('envoie les gestes sur la note choisie', async () => {
    const { edit_score, onEdited } = setup('n1')
    await screen.findByRole('button', { name: '▲ Plus haut' })
    await click('▲ Plus haut')
    expect(edit_score).toHaveBeenLastCalledWith(4, { op: 'pitch', symbol_id: 'n1', steps: 1 })
    expect(onEdited).toHaveBeenCalledWith('m12', 'n1')

    await click('♯ Dièse')
    expect(edit_score).toHaveBeenLastCalledWith(4, { op: 'alter', symbol_id: 'n1', alter: 1 })
    await click('blanche')
    expect(edit_score).toHaveBeenLastCalledWith(4, { op: 'duration', symbol_id: 'n1', written: '2', dots: 0 })
    await click('Ajouter une note après')
    expect(edit_score).toHaveBeenLastCalledWith(4, { op: 'add_note', measure_id: 'm12', after: 'n1' })
    await click('Supprimer')
    expect(edit_score).toHaveBeenLastCalledWith(4, { op: 'remove', symbol_id: 'n1' })
  })

  it('raccourcis clavier : flèches et Suppr', async () => {
    const { edit_score } = setup('n1')
    await screen.findByText('Mesure 12')
    await act(async () => {
      fireEvent.keyDown(window, { key: 'ArrowDown' })
    })
    expect(edit_score).toHaveBeenLastCalledWith(4, { op: 'pitch', symbol_id: 'n1', steps: -1 })
    await act(async () => {
      fireEvent.keyDown(window, { key: 'Delete' })
    })
    expect(edit_score).toHaveBeenLastCalledWith(4, { op: 'remove', symbol_id: 'n1' })
  })

  it('change les réglages de la mesure et annule', async () => {
    const { edit_score, undo_edit, onEdited } = setup()
    await screen.findByText('Mesure 12')
    fireEvent.change(screen.getByLabelText('Armure'), { target: { value: '2' } })
    expect(edit_score).toHaveBeenLastCalledWith(4, { op: 'key', measure_id: 'm12', fifths: 2 })
    await screen.findByText('Mesure 12')
    fireEvent.change(screen.getByLabelText('Clé'), { target: { value: 'F:4:0' } })
    expect(edit_score).toHaveBeenLastCalledWith(4, { op: 'clef', measure_id: 'm12', sign: 'F', line: 4, octave_change: 0 })
    await screen.findByText('Mesure 12')
    fireEvent.change(screen.getByLabelText('Nombre de temps'), { target: { value: '3' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Appliquer' })[0])
    expect(edit_score).toHaveBeenLastCalledWith(4, { op: 'time', measure_id: 'm12', beats: 3, beat_type: 4 })
    await screen.findByText('Mesure 12')
    fireEvent.change(screen.getByLabelText('Durée (mesures)'), { target: { value: '8' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Appliquer' })[1])
    expect(edit_score).toHaveBeenLastCalledWith(4, { op: 'multirest', measure_id: 'm12', count: 8 })
    await screen.findByText('Mesure 12')
    fireEvent.click(screen.getByRole('button', { name: 'Annuler ma dernière modification' }))
    expect(undo_edit).toHaveBeenCalledWith(4)
    await screen.findByText('Mesure 12')
    expect(onEdited).toHaveBeenLastCalledWith('m12', null)
  })

  it('affiche un geste refusé', async () => {
    const api = fakeApi({ get_measure: async () => details })
    render(<MeasureEditor api={api} scoreId={4} measureId="m12" symbolId="n1" version={0}
      onSelectSymbol={() => {}} onSelectMeasure={() => {}} onEdited={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Supprimer' }))
    expect(await screen.findByText("Cette modification n'a pas pu être faite.")).toBeInTheDocument()
  })

  it('nomme les symboles en anglais', async () => {
    await act(() => i18n.changeLanguage('en'))
    const label = symbolLabel(details.events[1], i18n.t, 'en')
    expect(label).toBe('C5, eighth note dotted')
    await act(() => i18n.changeLanguage('fr'))
  })
})
