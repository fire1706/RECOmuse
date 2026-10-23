// Zone des questions : une question à la fois, avec l'extrait de la partition et des
// choix cliquables. « Passer » remet la question à plus tard ; « Annuler ma dernière
// réponse » défait la dernière réponse (ses corrections sont annulées dans le journal).

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  type Choice,
  isError,
  type PythonApi,
  type Question,
  type QuestionsState,
} from './bridge'
import type { Language } from './i18n'
import { formatParams } from './music'

interface QuestionPanelProps {
  api: PythonApi
  scoreId: number
  /** Appelé après chaque réponse (le nombre de corrections a changé). */
  onAnswered?: () => void
}

/** Clé de traduction du texte d'une question (certaines dépendent d'un paramètre). */
export function questionTextKey(question: Question): string {
  if (question.code === 'note_out_of_range') {
    return `questions.text.note_out_of_range_${String(question.params.direction)}`
  }
  if (question.code === 'multirest_missed' && !question.params.count) {
    return 'questions.text.multirest_missed_no_count'
  }
  return `questions.text.${question.code}`
}

/** Les questions dans l'ordre où les poser : celles qu'on a passées vont à la fin. */
export function orderQuestions(questions: Question[], skipped: string[]): Question[] {
  const later = (q: Question) => skipped.indexOf(q.key)
  return [
    ...questions.filter((q) => later(q) < 0),
    ...questions.filter((q) => later(q) >= 0).sort((a, b) => later(a) - later(b)),
  ]
}

export default function QuestionPanel({ api, scoreId, onAnswered }: QuestionPanelProps) {
  const { t, i18n } = useTranslation()
  const language = (i18n.resolvedLanguage ?? 'fr') as Language
  const [state, setState] = useState<QuestionsState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [skipped, setSkipped] = useState<string[]>([])
  const [count, setCount] = useState('')

  // Questions de la partition choisie.
  useEffect(() => {
    let cancelled = false
    setState(null)
    setError(null)
    setSkipped([])
    api
      .get_questions(scoreId)
      .then((result) => {
        if (cancelled) return
        if (isError(result)) setError(result.error)
        else setState(result)
      })
      .catch(() => !cancelled && setError('unexpected'))
    return () => {
      cancelled = true
    }
  }, [api, scoreId])

  /** Envoie une demande au moteur et affiche le nouvel état des questions. */
  async function send(request: Promise<QuestionsState | { error: string }>) {
    setBusy(true)
    setError(null)
    try {
      const result = await request
      if (isError(result)) {
        setError(result.error)
      } else {
        setState(result)
        setCount('')
        onAnswered?.()
      }
    } catch {
      setError('unexpected')
    } finally {
      setBusy(false)
    }
  }

  if (state === null) {
    return error ? (
      <p className="error">{t(`errors.${error}`, { defaultValue: t('errors.unexpected') })}</p>
    ) : (
      <p className="empty">{t('questions.loading')}</p>
    )
  }

  const ordered = orderQuestions(state.questions, skipped)
  const question = ordered[0]

  const undoButton = state.can_undo && (
    <button type="button" className="link-button" disabled={busy}
      onClick={() => send(api.undo_answer(scoreId))}>
      {t('questions.undo')}
    </button>
  )

  if (!question) {
    return (
      <div className="questions-done">
        <p>{t('questions.done')}</p>
        {state.unasked > 0 && <p className="empty">{t('questions.unasked', { count: state.unasked })}</p>}
        {undoButton}
      </div>
    )
  }

  const params = formatParams(question.params, language)
  const answer = (choice: Choice, value: number | null = null) =>
    send(api.answer_question(scoreId, question.key, choice.id, value))

  return (
    <div className="question">
      <p className="question-progress">
        {t('questions.remaining', { count: state.questions.length })}
        {state.answered > 0 && ` · ${t('questions.answered', { count: state.answered })}`}
      </p>
      <p className="question-where">
        {t('questions.where', {
          measure: question.measure_numbers.slice(0, 3).join(', '),
          page: question.page ?? '?',
        })}
      </p>
      {question.image && (
        <img className="question-image" src={question.image} alt={t('questions.imageAlt')} />
      )}
      <p className="question-text">{t(questionTextKey(question), params)}</p>
      {question.issue_count > 1 && (
        <p className="question-note">{t('questions.grouped', { count: question.issue_count })}</p>
      )}

      <div className="choices">
        {question.choices.map((choice) =>
          choice.input === 'count' ? (
            <form key={choice.id} className="choice-input"
              onSubmit={(event) => {
                event.preventDefault()
                const value = Number.parseInt(count, 10)
                if (value >= 1) answer(choice, value)
              }}>
              <label>
                {t(`questions.choices.${choice.label}`, formatParams(choice.params, language))}
                <input type="number" min={1} value={count} disabled={busy}
                  onChange={(e) => setCount(e.target.value)} />
              </label>
              <button type="submit" disabled={busy || !(Number.parseInt(count, 10) >= 1)}>
                {t('questions.validate')}
              </button>
            </form>
          ) : (
            <button key={choice.id} type="button" className="choice" disabled={busy}
              onClick={() => answer(choice)}>
              {t(`questions.choices.${choice.label}`, formatParams(choice.params, language))}
            </button>
          ),
        )}
      </div>

      {error && <p className="error">{t(`errors.${error}`, { defaultValue: t('errors.unexpected') })}</p>}

      <div className="question-actions">
        <button type="button" className="link-button" disabled={busy || ordered.length < 2}
          onClick={() => setSkipped([...skipped.filter((k) => k !== question.key), question.key])}>
          {t('questions.skip')}
        </button>
        {undoButton}
      </div>
    </div>
  )
}
