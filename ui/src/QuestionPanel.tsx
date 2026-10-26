// Zone des questions : une question à la fois, avec l'extrait de la partition et des
// choix cliquables. « Passer » remet la question à plus tard ; « Annuler ma dernière
// réponse » défait la dernière réponse (ses corrections sont annulées dans le journal).

import { useEffect, useRef, useState } from 'react'
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
  /** Montre une mesure dans la vue côte à côte (question en cours, passage à vérifier). */
  onFocus?: (measureId: string | null, page: number | null) => void
}

/** Clé de traduction du texte d'une question (certaines dépendent d'un paramètre). */
export function questionTextKey(question: Question): string {
  if (question.code === 'note_out_of_range') {
    return `questions.text.note_out_of_range_${String(question.params.direction)}`
  }
  if (question.code === 'multirest_missed' && !question.params.count) {
    return 'questions.text.multirest_missed_no_count'
  }
  if (question.code === 'clef_sign_suspicious') {
    // Deux indices : l'étendue de l'instrument, ou une clé qui change en cours de partie.
    return `questions.text.clef_sign_suspicious_${String(question.params.reason)}`
  }
  if (question.code === 'time_signature_missed' && question.params.back) {
    // Passage dans un autre chiffrage, qui revient ensuite à l'ancien.
    return 'questions.text.time_signature_missed_section'
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

export default function QuestionPanel({ api, scoreId, onAnswered, onFocus }: QuestionPanelProps) {
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

  const ordered = state ? orderQuestions(state.questions, skipped) : []
  const question = ordered[0]

  // La question en cours est montrée dans la vue côte à côte (une fois par question :
  // l'utilisateur peut ensuite regarder ailleurs).
  const focus = useRef(onFocus)
  focus.current = onFocus
  const focusMeasure = question?.measure_id ?? null
  const focusPage = question?.page ?? null
  const focusKey = question?.key
  useEffect(() => {
    if (focusKey) focus.current?.(focusMeasure, focusPage)
  }, [focusKey, focusMeasure, focusPage])

  if (state === null) {
    return error ? (
      <p className="error">{t(`errors.${error}`, { defaultValue: t('errors.unexpected') })}</p>
    ) : (
      <p className="empty">{t('questions.loading')}</p>
    )
  }

  const undoButton = state.can_undo && (
    <button type="button" className="link-button" disabled={busy}
      onClick={() => send(api.undo_answer(scoreId))}>
      {t('questions.undo')}
    </button>
  )

  // Passages à vérifier à l'œil : un clic les montre dans la vue côte à côte.
  const checks = state.checks.length > 0 && (
    <details className="checks" open={!question}>
      <summary>{t('checks.title', { count: state.checks.length })}</summary>
      <ul>
        {state.checks.map((check, k) => (
          <li key={k}>
            <button type="button" className="link-button"
              onClick={() => onFocus?.(check.measure_id, check.page)}>
              {t('checks.where', { measure: check.measure_numbers.slice(0, 3).join(', ') })}
            </button>{' '}
            {t(`checks.${check.code}`, { ...check.details, defaultValue: t('checks.other') })}
          </li>
        ))}
      </ul>
    </details>
  )

  // Réponses données sans poser de question : règles apprises, lecture précédente.
  const byOthers = (state.answered_by_rules > 0 || state.answered_by_memory > 0) && (
    <p className="question-note">
      {state.answered_by_rules > 0 && t('questions.byRules', { count: state.answered_by_rules })}
      {state.answered_by_rules > 0 && state.answered_by_memory > 0 && ' '}
      {state.answered_by_memory > 0 && t('questions.byMemory', { count: state.answered_by_memory })}
    </p>
  )

  if (!question) {
    return (
      <div className="questions-done">
        <p>{t('questions.done')}</p>
        {byOthers}
        {state.unasked > 0 && <p className="empty">{t('questions.unasked', { count: state.unasked })}</p>}
        {checks}
        {undoButton}
      </div>
    )
  }

  const params = formatParams(question.params, language)
  if (question.code === 'measures_merge_suspicious') {
    // Les deux mesures qui n'en feraient qu'une.
    params.first = question.measure_numbers[0]
    params.second = question.measure_numbers[1]
  }
  if (question.code === 'clef_sign_suspicious') {
    // Noms des clés (« clé de sol »...), traduits.
    params.read = t(`questions.clefs.${String(question.params.read)}`)
    params.proposed = t(`questions.clefs.${String(question.params.proposed)}`)
  }
  const answer = (choice: Choice, value: number | null = null) =>
    send(api.answer_question(scoreId, question.key, choice.id, value))

  return (
    <div className="question">
      <p className="question-progress">
        {t('questions.remaining', { count: state.questions.length })}
        {state.answered > 0 && ` · ${t('questions.answered', { count: state.answered })}`}
        {state.compared_parts > 0 && ` · ${t('questions.compared', { count: state.compared_parts })}`}
      </p>
      {byOthers}
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
      {checks}
    </div>
  )
}
