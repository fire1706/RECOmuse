// Tests de la zone des questions, avec un faux moteur.

import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from './i18n'
import QuestionPanel, { orderQuestions, questionTextKey } from './QuestionPanel'
import { fakeApi, noteQuestion, questionsState, restQuestion } from './testFakes'

describe('QuestionPanel', () => {
  beforeEach(async () => {
    await act(() => i18n.changeLanguage('fr'))
  })
  afterEach(async () => {
    await act(() => i18n.changeLanguage('fr'))
  })

  it("montre la question, son extrait et ses choix", async () => {
    const api = fakeApi({ get_questions: async () => questionsState([restQuestion, noteQuestion]) })
    render(<QuestionPanel api={api} scoreId={1} />)

    expect(await screen.findByText(/Est-ce une pause de 8 mesures/)).toBeInTheDocument()
    expect(screen.getByText('2 questions restantes')).toBeInTheDocument()
    expect(screen.getByText('Mesure 3, page 1')).toBeInTheDocument()
    expect(screen.getByRole('img')).toHaveAttribute('src', restQuestion.image)
    expect(screen.getByRole('button', { name: 'Oui, 8 mesures' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Non, une seule mesure' })).toBeInTheDocument()
    expect(screen.getByLabelText('Nombre de mesures :')).toBeInTheDocument()
  })

  it('envoie la réponse cliquée et affiche les questions suivantes', async () => {
    const answer_question = vi.fn(async () => questionsState([noteQuestion], { answered: 1, can_undo: true }))
    const onAnswered = vi.fn()
    const api = fakeApi({
      get_questions: async () => questionsState([restQuestion, noteQuestion]),
      answer_question,
    })
    render(<QuestionPanel api={api} scoreId={7} onAnswered={onAnswered} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Oui, 8 mesures' }))
    expect(await screen.findByText('Quelle est la note entourée ?')).toBeInTheDocument()
    expect(answer_question).toHaveBeenCalledWith(7, restQuestion.key, 'accept', null)
    expect(onAnswered).toHaveBeenCalled()
    // Les notes sont écrites en solfège.
    expect(screen.getByRole('button', { name: 'do6' })).toBeInTheDocument()
    expect(screen.getByText(/1 réponse donnée/)).toBeInTheDocument()
  })

  it('envoie le nombre tapé', async () => {
    const answer_question = vi.fn(async () => questionsState([]))
    const api = fakeApi({ get_questions: async () => questionsState([restQuestion]), answer_question })
    render(<QuestionPanel api={api} scoreId={1} />)

    const input = await screen.findByLabelText('Nombre de mesures :')
    const ok = screen.getByRole('button', { name: 'Valider' })
    expect(ok).toBeDisabled()
    fireEvent.change(input, { target: { value: '12' } })
    fireEvent.click(ok)
    expect(await screen.findByText(/Toutes les questions ont une réponse/)).toBeInTheDocument()
    expect(answer_question).toHaveBeenCalledWith(1, restQuestion.key, 'count', 12)
  })

  it('« Passer » remet la question à plus tard', async () => {
    const api = fakeApi({ get_questions: async () => questionsState([restQuestion, noteQuestion]) })
    render(<QuestionPanel api={api} scoreId={1} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Passer (reposer plus tard)' }))
    expect(screen.getByText('Quelle est la note entourée ?')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Passer (reposer plus tard)' }))
    expect(screen.getByText(/Est-ce une pause de 8 mesures/)).toBeInTheDocument()
  })

  it('annule la dernière réponse', async () => {
    const undo_answer = vi.fn(async () => questionsState([restQuestion], { answered: 0 }))
    const api = fakeApi({
      get_questions: async () => questionsState([], { answered: 1, can_undo: true, unasked: 2 }),
      undo_answer,
    })
    render(<QuestionPanel api={api} scoreId={3} />)

    expect(await screen.findByText(/Toutes les questions ont une réponse/)).toBeInTheDocument()
    expect(screen.getByText(/2 passages restent à vérifier/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Annuler ma dernière réponse' }))
    expect(await screen.findByText(/Est-ce une pause de 8 mesures/)).toBeInTheDocument()
    expect(undo_answer).toHaveBeenCalledWith(3)
  })

  it('affiche une erreur du moteur', async () => {
    const api = fakeApi({
      get_questions: async () => questionsState([restQuestion]),
      answer_question: async () => ({ error: 'question_failed' }),
    })
    render(<QuestionPanel api={api} scoreId={1} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Oui, 8 mesures' }))
    expect(await screen.findByText("Cette réponse n'a pas pu être enregistrée.")).toBeInTheDocument()
  })

  it("pose les questions issues de la comparaison entre parties", async () => {
    const question = {
      ...restQuestion,
      key: 'multirest:P1:m82',
      code: 'part_measures_missing',
      params: { count: 8, difference: 7, read: 1 },
      choices: [
        { id: 'accept', label: 'rest_measures', params: { count: 8 }, input: null },
        { id: 'keep', label: 'rest_as_read', params: { count: 1 }, input: null },
      ],
    }
    const api = fakeApi({ get_questions: async () => questionsState([question], { compared_parts: 16 }) })
    render(<QuestionPanel api={api} scoreId={1} />)
    expect(await screen.findByText(/Les autres parties du morceau ont 7 mesure\(s\) de plus ici/)).toBeInTheDocument()
    expect(screen.getByText(/Comparée aux 16 autres parties du morceau/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Non, une seule mesure, comme lu' })).toBeInTheDocument()
  })

  it('montre la question en cours et les passages à vérifier dans la vue côte à côte', async () => {
    const onFocus = vi.fn()
    const check = { code: 'measure_duration', measure_numbers: [12], measure_id: 'm12', page: 2,
      details: { read: '3', expected: '4' } }
    const api = fakeApi({ get_questions: async () => questionsState([restQuestion], { checks: [check], unasked: 1 }) })
    render(<QuestionPanel api={api} scoreId={1} onFocus={onFocus} />)
    await screen.findByText(/Est-ce une pause de 8 mesures/)
    expect(onFocus).toHaveBeenCalledWith('m3', 1)

    expect(screen.getByText("1 passage à vérifier à l'œil")).toBeInTheDocument()
    expect(screen.getByText(/la mesure compte 3 noire\(s\) au lieu de 4/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Mesure 12' }))
    expect(onFocus).toHaveBeenLastCalledWith('m12', 2)
  })

  it('demande la clé en la nommant, et propose les deux clés', async () => {
    const clef = {
      ...restQuestion, key: 'clef', code: 'clef_sign_suspicious',
      params: { read: 'treble', proposed: 'bass', notes: 24, reason: 'change' },
      choices: [
        { id: 'accept', label: 'clef_bass', params: {}, input: null },
        { id: 'keep', label: 'clef_treble', params: {}, input: null },
      ],
    }
    render(<QuestionPanel api={fakeApi({ get_questions: async () => questionsState([clef]) })} scoreId={1} />)
    expect(await screen.findByText(
      /lue comme une clé de sol, alors que la partie était en clé de fa jusqu'ici.*les 24 notes/,
    )).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Une clé de fa' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Une clé de sol' })).toBeInTheDocument()
  })

  it('propose un passage dans un autre chiffrage, avec le retour au chiffrage d’avant', async () => {
    const section = {
      ...restQuestion, key: 'time', code: 'time_signature_missed',
      params: { time: '2/4', back: '4/4', first: 12, last: 13, measures: 2 },
      choices: [{ id: 'accept', label: 'time_section', params: { time: '2/4', back: '4/4' }, input: null }],
    }
    render(<QuestionPanel api={fakeApi({ get_questions: async () => questionsState([section]) })} scoreId={1} />)
    expect(await screen.findByText(/Les mesures 12 à 13 .* à 2\/4, avant de revenir à 4\/4/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Oui, 2/4, puis de nouveau 4/4' })).toBeInTheDocument()
  })

  it('parle anglais', async () => {
    await act(() => i18n.changeLanguage('en'))
    const api = fakeApi({ get_questions: async () => questionsState([noteQuestion]) })
    render(<QuestionPanel api={api} scoreId={1} />)
    expect(await screen.findByText('What is the circled note?')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'C6' })).toBeInTheDocument()
  })
})

describe('outils des questions', () => {
  it('choisit le texte selon le sens ou le nombre connu', () => {
    const high = { ...noteQuestion, code: 'note_out_of_range', params: { direction: 'high' } }
    expect(questionTextKey(high)).toBe('questions.text.note_out_of_range_high')
    const unknown = { ...restQuestion, params: { count: null } }
    expect(questionTextKey(unknown)).toBe('questions.text.multirest_missed_no_count')
    expect(questionTextKey(restQuestion)).toBe('questions.text.multirest_missed')
  })

  it('met les questions passées à la fin, dans l’ordre où elles ont été passées', () => {
    const third = { ...noteQuestion, key: 'c' }
    const order = orderQuestions([restQuestion, noteQuestion, third], [noteQuestion.key, restQuestion.key])
    expect(order.map((q) => q.key)).toEqual(['c', noteQuestion.key, restQuestion.key])
  })
})
