// Tests des avertissements de lecture (image trop petite, page non lue, page penchée).

import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import App from './App'
import i18n from './i18n'
import ReadingWarnings from './ReadingWarnings'
import { fakeApi } from './testFakes'

describe('ReadingWarnings', () => {
  beforeEach(async () => {
    await act(() => i18n.changeLanguage('fr'))
    window.localStorage.clear()
  })

  it('dit ce qui ne va pas, et quoi faire', () => {
    render(
      <ReadingWarnings
        warnings={[
          { code: 'low_resolution', pages: [1], dpi: 68 },
          { code: 'audiveris_skipped', pages: [3, 4] },
        ]}
      />,
    )
    const list = screen.getByRole('list', { name: 'Remarques sur la lecture' })
    expect(within(list).getByText(/environ 68 dpi, page 1\).*scannez la partition à 300 dpi/)).toBeInTheDocument()
    expect(within(list).getByText(/n'a pas pu lire les pages 3, 4/)).toBeInTheDocument()
  })

  it("ne montre rien quand la lecture n'a rien remarqué", () => {
    const { container } = render(<ReadingWarnings warnings={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('apparaît sur la carte de la partition et dans le panneau des questions', async () => {
    const tuba = {
      score_id: 1, title: 'Grown-up Christmas List', instrument: 'Tuba', source_name: 'tuba.bmp',
      pages: [1], measure_count: 47, instruments: [], derived: null,
      warnings: [{ code: 'low_resolution' as const, pages: [1], dpi: 68 }],
    }
    render(<App connect={async () => fakeApi({ list_scores: async () => [tuba] })} />)
    const card = await screen.findByRole('button', { name: /Tuba/ })
    expect(within(card).getByText('⚠ Lecture à vérifier')).toBeInTheDocument()

    fireEvent.click(card)
    expect(await screen.findByText(/environ 68 dpi/)).toBeInTheDocument()
  })
})
