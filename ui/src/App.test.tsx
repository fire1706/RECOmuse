// Tests de l'écran principal, avec un faux pont Python (aucune fenêtre pywebview).

import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import App from './App'
import type { AppInfo, PythonApi } from './bridge'
import i18n from './i18n'

const fakeInfo: AppInfo = {
  version: '0.1.0',
  python_version: '3.12.10',
  platform: 'win32',
  database_path: 'C:/fictif/recomuse.sqlite3',
  correction_count: 3,
}

function fakeApi(info: AppInfo = fakeInfo): PythonApi {
  return {
    ping: async () => 'pong',
    get_app_info: async () => info,
  }
}

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
      <App connect={async () => fakeApi({ ...fakeInfo, correction_count: 1 })} />,
    )
    expect(await screen.findByText(/1 correction mémorisée/)).toBeInTheDocument()
    unmount()

    render(<App connect={async () => fakeApi({ ...fakeInfo, correction_count: 0 })} />)
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
})
