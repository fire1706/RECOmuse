// Tests de l'écran principal, avec un faux pont Python (aucune fenêtre pywebview).

import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import i18n from './i18n'
import { fakeApi, fakeInfo, questionsState, restQuestion } from './testFakes'

describe('App', () => {
  afterEach(async () => {
    await act(() => i18n.changeLanguage('fr'))
  })

  it('affiche les trois zones de travail', async () => {
    await act(() => i18n.changeLanguage('fr'))
    render(<App connect={async () => fakeApi()} />)
    expect(screen.getByRole('heading', { name: "Partition d'origine" })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Questions' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Partition reconnue' })).toBeInTheDocument()
    // Laisse la connexion simulée se terminer avant la fin du test.
    await screen.findByText(/Moteur prêt/)
  })

  it('affiche les informations du moteur une fois connecté', async () => {
    render(<App connect={async () => fakeApi()} />)
    const status = await screen.findByRole('status')
    expect(await screen.findByText(/Moteur prêt \(version 0\.1\.0, Python 3\.12\.10\)/)).toBeInTheDocument()
    expect(status).toHaveTextContent('3 corrections mémorisées')
  })

  it('gère le singulier et le cas zéro', async () => {
    const { unmount } = render(
      <App connect={async () => fakeApi({}, { ...fakeInfo, correction_count: 1 })} />,
    )
    expect(await screen.findByText(/1 correction mémorisée/)).toBeInTheDocument()
    unmount()

    render(<App connect={async () => fakeApi({}, { ...fakeInfo, correction_count: 0 })} />)
    expect(await screen.findByText(/Aucune correction mémorisée/)).toBeInTheDocument()
  })

  it('signale un moteur absent (interface ouverte dans un navigateur)', async () => {
    render(<App connect={async () => null} />)
    expect(await screen.findByText(/Moteur indisponible/)).toBeInTheDocument()
  })

  it('signale un moteur en erreur', async () => {
    render(<App connect={async () => Promise.reject(new Error('panne'))} />)
    expect(await screen.findByText(/Moteur indisponible/)).toBeInTheDocument()
  })

  it("change de langue avec le sélecteur", async () => {
    render(<App connect={async () => fakeApi()} />)
    await screen.findByText(/Moteur prêt/)

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'en' } })

    expect(await screen.findByRole('heading', { name: 'Original score' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('3 corrections remembered')
  })

  it('ouvre une partition, montre la lecture puis la première question', async () => {
    let finish: (value: unknown) => void = () => {}
    const open_file = vi.fn(() => new Promise((resolve) => (finish = resolve)))
    const api = fakeApi({
      choose_file: async () => 'C:/partitions/marche.pdf',
      open_file: open_file as never,
      get_questions: async () => questionsState([restQuestion]),
    })
    render(<App connect={async () => api} />)
    await screen.findByText(/Moteur prêt/)

    fireEvent.click(screen.getByRole('button', { name: 'Ouvrir une partition…' }))
    expect(await screen.findByText('Préparation des pages…')).toBeInTheDocument()
    expect(open_file).toHaveBeenCalledWith('C:/partitions/marche.pdf')

    await act(async () =>
      finish({
        scores: [
          { score_id: 1, title: 'Marche', instrument: 'Flûte', source_name: 'marche.pdf', pages: [1], measure_count: 40 },
        ],
      }),
    )
    expect(await screen.findByText(/Est-ce une pause de 8 mesures/)).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Marche — Flûte (40 mesures)' })).toBeInTheDocument()
  })

  it("affiche l'erreur d'une lecture impossible", async () => {
    const api = fakeApi({
      choose_file: async () => 'C:/partitions/secret.pdf',
      open_file: async () => ({ error: 'encrypted_pdf' }),
    })
    render(<App connect={async () => api} />)
    await screen.findByText(/Moteur prêt/)
    fireEvent.click(screen.getByRole('button', { name: 'Ouvrir une partition…' }))
    expect(await screen.findByText('Ce PDF est protégé par un mot de passe.')).toBeInTheDocument()
  })

  it("ne fait rien si l'utilisateur ferme la fenêtre « Ouvrir »", async () => {
    const open_file = vi.fn()
    render(<App connect={async () => fakeApi({ open_file })} />)
    await screen.findByText(/Moteur prêt/)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Ouvrir une partition…' })))
    expect(open_file).not.toHaveBeenCalled()
  })
})
