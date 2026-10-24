// Tests de la fenêtre « Exporter », avec un faux moteur.

import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ExportOptions } from './bridge'
import ExportDialog from './ExportDialog'
import i18n from './i18n'
import { fakeApi } from './testFakes'

function setup(options: Partial<ExportOptions> = {}, fallback: string | null = null) {
  const choose_save_path = vi.fn(async () => 'C:/Partitions/Marche - Trompette.mscz')
  const export_score = vi.fn(async () => ({
    path: fallback ? 'C:/Partitions/Marche - Trompette.musicxml' : 'C:/Partitions/Marche - Trompette.mscz',
    format: fallback ? ('musicxml' as const) : ('musescore' as const),
    fallback,
  }))
  const api = fakeApi({
    get_export_options: async () => ({ default_name: 'Marche - Trompette', musescore: true, questions: 0, checks: 0, ...options }),
    choose_save_path,
    export_score,
  })
  const onClose = vi.fn()
  render(<ExportDialog api={api} scoreId={5} onClose={onClose} />)
  return { choose_save_path, export_score, onClose }
}

describe('ExportDialog', () => {
  beforeEach(async () => {
    await act(() => i18n.changeLanguage('fr'))
  })

  it('enregistre pour MuseScore par défaut', async () => {
    const { choose_save_path, export_score } = setup()
    expect(await screen.findByText('MuseScore (.mscz)')).toBeInTheDocument()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Enregistrer…' }))
    })
    expect(choose_save_path).toHaveBeenCalledWith('Partition MuseScore', 'Marche - Trompette', 'musescore')
    expect(export_score).toHaveBeenCalledWith(5, 'musescore', 'C:/Partitions/Marche - Trompette.mscz')
    expect(screen.getByText('Enregistré : C:/Partitions/Marche - Trompette.mscz')).toBeInTheDocument()
  })

  it('choisit le MIDI, et ne fait rien si on ferme la fenêtre « Enregistrer »', async () => {
    const { choose_save_path, export_score } = setup()
    await screen.findByText('MuseScore (.mscz)')
    fireEvent.click(screen.getByRole('radio', { name: /MIDI/ }))
    choose_save_path.mockResolvedValueOnce(null as never)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Enregistrer…' }))
    })
    expect(choose_save_path).toHaveBeenCalledWith('Fichier MIDI', 'Marche - Trompette', 'midi')
    expect(export_score).not.toHaveBeenCalled()
  })

  it('prévient des doutes restants et de l’absence de MuseScore', async () => {
    setup({ musescore: false, questions: 2, checks: 1 }, 'musescore_not_found')
    expect(await screen.findByText(/MuseScore n'est pas installé/)).toBeInTheDocument()
    expect(screen.getByText(/il reste 2 questions sans réponse et 1 passage à vérifier/)).toBeInTheDocument()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Enregistrer…' }))
    })
    expect(screen.getByText('MuseScore est introuvable : la partition a été enregistrée en MusicXML.')).toBeInTheDocument()
  })
})
