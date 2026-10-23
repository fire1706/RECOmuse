// Tests de la vue côte à côte : page d'origine (ScanView) et rendu (ScoreView), avec un
// faux moteur et un faux Verovio.

import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { PageView, Rendering } from './bridge'
import i18n from './i18n'
import ScanView, { boxStyle } from './ScanView'
import ScoreView from './ScoreView'
import { fakeApi } from './testFakes'

const page5: PageView = {
  score_id: 1,
  page: 5,
  image: 'data:image/jpeg;base64,AAAA',
  width: 2000,
  height: 1000,
  measures: [
    { id: 'm1', number: 1, length: 1, part_id: 'P1', bbox: [100, 100, 400, 200] },
    { id: 'm2', number: 2, length: 8, part_id: 'P1', bbox: [500, 100, 400, 200] },
  ],
  pages: [5, 6],
}

const rendering: Rendering = {
  score_id: 1,
  mei: '<mei/>',
  symbols: {},
  measures: { 'm-m1': 'm1', 'm-m2': 'm2' },
  measure_pages: { m1: 5, m2: 6 },
}

/** Faux Verovio : un dessin avec deux mesures. */
const fakeRender = async () => [
  '<svg><g id="m-m1" class="measure"><path d="M0 0"/></g><g id="m-m2" class="measure"><path d="M1 1"/></g></svg>',
]

describe('ScanView', () => {
  beforeEach(async () => {
    await act(() => i18n.changeLanguage('fr'))
  })

  it('montre la page et encadre ses mesures', async () => {
    const onSelect = vi.fn()
    const onPage = vi.fn()
    const api = fakeApi({ get_page: async () => page5 })
    render(<ScanView api={api} scoreId={1} page={5} version={0} selectedMeasure="m2"
      onPage={onPage} onSelect={onSelect} />)

    expect(await screen.findByRole('img', { name: 'Page 5 de la partition d\'origine' })).toBeInTheDocument()
    expect(screen.getByText('Page 5 (2 pages de musique)')).toBeInTheDocument()
    const second = screen.getByRole('button', { name: 'Mesure 2' })
    expect(second).toHaveClass('selected')
    expect(second).toHaveStyle({ left: '25%', top: '10%', width: '20%', height: '20%' })

    fireEvent.click(screen.getByRole('button', { name: 'Mesure 1' }))
    expect(onSelect).toHaveBeenCalledWith('m1', 5)
    expect(screen.getByRole('button', { name: '◀ Page précédente' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Page suivante ▶' }))
    expect(onPage).toHaveBeenCalledWith(6)
  })

  it('signale une page introuvable', async () => {
    render(<ScanView api={fakeApi()} scoreId={1} page={5} version={0} selectedMeasure={null}
      onPage={() => {}} onSelect={() => {}} />)
    expect(await screen.findByText('Cette page est introuvable.')).toBeInTheDocument()
  })

  it('place les boîtes en pourcentages de la page', () => {
    expect(boxStyle([0, 50, 100, 25], 200, 100)).toEqual({ left: '0%', top: '50%', width: '50%', height: '25%' })
  })
})

describe('ScoreView', () => {
  it('dessine la partition, surligne la mesure choisie et renvoie celle qu’on clique', async () => {
    const onSelect = vi.fn()
    const api = fakeApi({ get_rendering: async () => rendering })
    const { container, rerender } = render(
      <ScoreView api={api} scoreId={1} version={0} selectedMeasure="m1" onSelect={onSelect} render={fakeRender} />,
    )
    await screen.findByRole('presentation')
    expect(container.querySelector('#m-m1')).toHaveClass('selected')

    rerender(<ScoreView api={api} scoreId={1} version={0} selectedMeasure="m2" onSelect={onSelect} render={fakeRender} />)
    expect(container.querySelector('#m-m1')).not.toHaveClass('selected')
    expect(container.querySelector('#m-m2')).toHaveClass('selected')

    fireEvent.click(container.querySelector('#m-m2 path')!)
    expect(onSelect).toHaveBeenCalledWith('m2', 6)
  })

  it('signale un dessin impossible', async () => {
    const api = fakeApi({ get_rendering: async () => rendering })
    const failing = async () => {
      throw new Error('MEI illisible')
    }
    render(<ScoreView api={api} scoreId={1} version={0} selectedMeasure={null} onSelect={() => {}} render={failing} />)
    expect(await screen.findByText("La partition n'a pas pu être dessinée.")).toBeInTheDocument()
  })
})
