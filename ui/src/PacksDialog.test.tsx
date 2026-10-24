// Tests de la fenêtre « Packs d'apprentissage », avec un faux moteur.

import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { PackInfo } from './bridge'
import i18n from './i18n'
import PacksDialog from './PacksDialog'
import { fakeApi } from './testFakes'

const claire: PackInfo = {
  id: 3, author: 'Claire', created_at: '2026-10-20T10:00:00+00:00', imported_at: '2026-10-21T08:00:00.000Z',
  answers: 12, scores: 4,
}

describe('PacksDialog', () => {
  beforeEach(async () => {
    await act(() => i18n.changeLanguage('fr'))
  })

  it('crée un pack avec le nom de son auteur', async () => {
    const choose_pack_file = vi.fn(async () => 'C:/Packs/RECOmuse - Marc.recomuse-pack')
    const export_pack = vi.fn(async () => ({ path: 'C:/Packs/RECOmuse - Marc.recomuse-pack', answers: 7, scores: 1 }))
    render(<PacksDialog api={fakeApi({ choose_pack_file, export_pack })} onClose={() => {}} />)
    expect(await screen.findByText('Aucun pack importé.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Votre nom (facultatif)'), { target: { value: 'Marc' } })
    fireEvent.click(screen.getByLabelText('Inclure les corrections de mes parties'))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Créer un pack…' }))
    })
    expect(choose_pack_file).toHaveBeenCalledWith(true, "Pack d'apprentissage RECOmuse", 'RECOmuse - Marc')
    expect(export_pack).toHaveBeenCalledWith('C:/Packs/RECOmuse - Marc.recomuse-pack', 'Marc', false)
    expect(screen.getByRole('status')).toHaveTextContent('7 réponses, 1 partie corrigée')
  })

  it('importe un pack, le montre et le retire', async () => {
    const onChanged = vi.fn()
    const list_packs = vi.fn().mockResolvedValueOnce([]).mockResolvedValueOnce([claire])
    const api = fakeApi({
      choose_pack_file: async () => 'C:/Reçus/claire.recomuse-pack',
      import_pack: async () => claire,
      list_packs,
      remove_pack: async () => ({ packs: [] }),
    })
    render(<PacksDialog api={api} onClose={() => {}} onChanged={onChanged} />)
    await screen.findByText('Aucun pack importé.')
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Importer un pack…' }))
    })
    expect(screen.getByText(/Pack de Claire, créé le .* : 12 réponses, 4 parties corrigées\./)).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Pack de Claire importé')
    expect(onChanged).toHaveBeenCalledTimes(1)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Retirer' }))
    })
    expect(screen.getByText('Aucun pack importé.')).toBeInTheDocument()
    expect(onChanged).toHaveBeenCalledTimes(2)
  })

  it('explique un fichier refusé', async () => {
    const api = fakeApi({
      choose_pack_file: async () => 'C:/Reçus/photo.recomuse-pack',
      import_pack: async () => ({ error: 'not_a_pack' }),
    })
    render(<PacksDialog api={api} onClose={() => {}} />)
    await screen.findByText('Aucun pack importé.')
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Importer un pack…' }))
    })
    expect(screen.getByText("Ce fichier n'est pas un pack d'apprentissage RECOmuse.")).toBeInTheDocument()
  })
})
