// Tests de la fenêtre « Règles apprises » et des messages de la mémoire des partitions.

import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { Rule } from './bridge'
import i18n from './i18n'
import QuestionPanel from './QuestionPanel'
import RulesDialog, { ruleAnswer, ruleContext } from './RulesDialog'
import { fakeApi, questionsState } from './testFakes'

const noteRule: Rule = {
  key: '{"code": "note_position_mismatch", "place": "above", "shift": "octave"}',
  signature: { code: 'note_position_mismatch', place: 'above', shift: 'octave' },
  choice_id: 'accept',
  choice_label: 'note',
  evidence: 5,
  agreeing: 5,
  enabled: true,
}

describe('RulesDialog', () => {
  beforeEach(async () => {
    await act(() => i18n.changeLanguage('fr'))
  })

  it('décrit les règles et permet de les désactiver', async () => {
    const set_rule_enabled = vi.fn(async () => ({ rules: [{ ...noteRule, enabled: false }] }))
    const api = fakeApi({ get_rules: async () => [noteRule], set_rule_enabled })
    render(<RulesDialog api={api} onClose={() => {}} />)
    expect(
      await screen.findByText('Note lue une octave à côté de sa position sur la portée (au-dessus de la portée)'),
    ).toBeInTheDocument()
    expect(screen.getByText(/prendre la note d'après sa position/)).toBeInTheDocument()
    expect(screen.getByText('5 réponses identiques sur 5')).toBeInTheDocument()
    const box = screen.getByRole('checkbox')
    expect(box).toBeChecked()
    await act(async () => {
      fireEvent.click(box)
    })
    expect(set_rule_enabled).toHaveBeenCalledWith(noteRule.key, false)
    expect(screen.getByRole('checkbox')).not.toBeChecked()
  })

  it('dit quand il n’y a pas encore de règle', async () => {
    render(<RulesDialog api={fakeApi()} onClose={() => {}} />)
    expect(await screen.findByText(/Aucune règle pour l'instant/)).toBeInTheDocument()
  })

  it('a des textes de secours pour un doute ou une réponse inconnus', () => {
    const odd: Rule = { ...noteRule, signature: { code: 'nouveau' }, choice_id: 'keep' }
    expect(ruleContext(odd, i18n.t)).toBe('Doute « nouveau »')
    expect(ruleAnswer(odd, i18n.t)).toBe('garder ce qui a été lu')
  })
})

describe('mémoire et règles dans les autres écrans', () => {
  beforeEach(async () => {
    await act(() => i18n.changeLanguage('fr'))
  })

  it('annonce une partie déjà lue à son ouverture', async () => {
    const api = fakeApi({
      choose_file: async () => 'C:/partitions/marche.pdf',
      open_file: async () => ({
        scores: [{
          score_id: 4, title: 'Marche', instrument: 'Flûte', source_name: 'marche.pdf', pages: [1], measure_count: 40,
          memory: { from: 1, applied: 12, skipped: 1, answers: 3, read_at: '2026-10-20T10:00:00.000Z' },
        }],
      }),
    })
    render(<App connect={async () => api} />)
    await screen.findByText(/Moteur prêt/)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Ouvrir une partition…' }))
    })
    expect(await screen.findByText(/Flûte : déjà lue le .* ; 12 corrections et 3 réponses reprises/)).toHaveTextContent(
      "(1 correction ne s'appliquait plus.)",
    )
  })

  it('compte les réponses données par les règles et la mémoire', async () => {
    const api = fakeApi({ get_questions: async () => questionsState([], { answered_by_rules: 2, answered_by_memory: 1 }) })
    render(<QuestionPanel api={api} scoreId={1} />)
    expect(
      await screen.findByText('2 réponses données par les règles apprises. 1 réponse reprise d\'une lecture précédente.'),
    ).toBeInTheDocument()
  })
})
