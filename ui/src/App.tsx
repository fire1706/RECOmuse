// Écran principal de RECOmuse.
//
// Disposition prévue par le cahier des charges :
//   à gauche le scan d'origine, au centre les questions, à droite le rendu Verovio.
// Tâche 8 : ouverture d'une partition et questions guidées (zone du centre).
// Les zones de gauche et de droite seront remplies à la tâche 9 (vue côte à côte).

import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { type AppInfo, isError, type PythonApi, type ScoreSummary, waitForBridge } from './bridge'
import { SUPPORTED_LANGUAGES } from './i18n'
import QuestionPanel from './QuestionPanel'
import './App.css'

/** État de la connexion au moteur Python. */
type EngineState =
  | { kind: 'connecting' }
  | { kind: 'connected'; api: PythonApi; info: AppInfo }
  | { kind: 'unavailable' }

/** Intervalle entre deux demandes « où en est la lecture ? », en millisecondes. */
const PROGRESS_INTERVAL_MS = 700

interface AppProps {
  /** Permet aux tests de fournir un faux pont ; par défaut, le vrai pont pywebview. */
  connect?: () => Promise<PythonApi | null>
}

/** Nom d'une partition dans la liste : son instrument (le morceau est le titre du groupe). */
function scoreLabel(score: ScoreSummary, unknown: string): string {
  return score.instrument ?? score.source_name ?? unknown
}

/**
 * Regroupe les partitions par morceau (même titre, comme le moteur pour les comparer),
 * dans l'ordre où les morceaux apparaissent dans la liste.
 */
export function groupByPiece(scores: ScoreSummary[], untitled: string): [string, ScoreSummary[]][] {
  const groups = new Map<string, [string, ScoreSummary[]]>()
  for (const score of scores) {
    const title = score.title ?? untitled
    const key = title.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, ' ').trim()
    if (!groups.has(key)) groups.set(key, [title, []])
    groups.get(key)![1].push(score)
  }
  return [...groups.values()]
}

export default function App({ connect = waitForBridge }: AppProps) {
  const { t, i18n } = useTranslation()
  const [engine, setEngine] = useState<EngineState>({ kind: 'connecting' })
  const [scores, setScores] = useState<ScoreSummary[]>([])
  const [scoreId, setScoreId] = useState<number | null>(null)
  const [reading, setReading] = useState<string | null>(null) // étape de la lecture en cours
  const [openError, setOpenError] = useState<string | null>(null)
  const [openedParts, setOpenedParts] = useState<number | null>(null)
  const poll = useRef<number | null>(null)

  useEffect(() => {
    // « cancelled » évite de modifier l'écran s'il a été fermé entre-temps.
    let cancelled = false
    connect()
      .then(async (api) => {
        const info = api ? await api.get_app_info() : null
        if (cancelled) return
        if (api && info) {
          setEngine({ kind: 'connected', api, info })
          const known = await api.list_scores()
          if (!cancelled) setScores(known)
        } else {
          setEngine({ kind: 'unavailable' })
        }
      })
      .catch(() => {
        if (!cancelled) setEngine({ kind: 'unavailable' })
      })
    return () => {
      cancelled = true
      if (poll.current !== null) window.clearInterval(poll.current)
    }
  }, [connect])

  /** Relit le nombre de corrections (affiché dans la barre d'état). */
  const refreshInfo = useCallback(async () => {
    if (engine.kind !== 'connected') return
    const info = await engine.api.get_app_info()
    setEngine({ ...engine, info })
  }, [engine])

  async function openScore() {
    if (engine.kind !== 'connected') return
    const { api } = engine
    const path = await api.choose_file(t('open.filter'))
    if (!path) return
    setOpenError(null)
    setOpenedParts(null)
    setReading('import')
    poll.current = window.setInterval(async () => {
      const { stage } = await api.get_progress()
      if (stage) setReading(stage)
    }, PROGRESS_INTERVAL_MS)
    try {
      const result = await api.open_file(path)
      if (isError(result)) {
        setOpenError(result.error)
      } else {
        setScores([...result.scores, ...scores])
        setScoreId(result.scores[0]?.score_id ?? null)
        setOpenedParts(result.scores.length)
      }
    } catch {
      setOpenError('unexpected')
    } finally {
      if (poll.current !== null) window.clearInterval(poll.current)
      poll.current = null
      setReading(null)
    }
  }

  const connected = engine.kind === 'connected'

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>{t('app.title')}</h1>
          <p className="tagline">{t('app.tagline')}</p>
        </div>
        <div className="toolbar">
          <button type="button" onClick={openScore} disabled={!connected || reading !== null}>
            {t('open.button')}
          </button>
          {scores.length > 0 && (
            <label className="score-picker">
              {t('scores.label')}
              <select value={scoreId ?? ''} disabled={reading !== null}
                onChange={(e) => setScoreId(e.target.value ? Number(e.target.value) : null)}>
                <option value="">{t('scores.choose')}</option>
                {groupByPiece(scores, t('scores.unknownPiece')).map(([title, parts]) => (
                  <optgroup key={title} label={title}>
                    {parts.map((score) => (
                      <option key={score.score_id} value={score.score_id}>
                        {t('scores.item', {
                          name: scoreLabel(score, t('scores.untitled')),
                          count: score.measure_count,
                        })}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>
          )}
          <label className="language-picker">
            {t('language.label')}
            <select value={i18n.resolvedLanguage} onChange={(e) => i18n.changeLanguage(e.target.value)}>
              {SUPPORTED_LANGUAGES.map((lang) => (
                <option key={lang} value={lang}>
                  {lang.toUpperCase()}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      <main className="panels">
        <section className="panel" aria-labelledby="panel-scan">
          <h2 id="panel-scan">{t('panels.scan')}</h2>
          <p className="empty">{t('panels.scanEmpty')}</p>
        </section>
        <section className="panel panel-questions" aria-labelledby="panel-questions">
          <h2 id="panel-questions">{t('panels.questions')}</h2>
          {reading !== null && (
            <p className="reading" role="progressbar" aria-busy="true">
              {t(`open.stage.${reading}`, { defaultValue: t('open.stage.recognition') })}
            </p>
          )}
          {openedParts !== null && openedParts > 1 && (
            <p className="question-note">{t('open.parts', { count: openedParts })}</p>
          )}
          {openError && (
            <p className="error">{t(`errors.${openError}`, { defaultValue: t('errors.unexpected') })}</p>
          )}
          {reading === null && engine.kind === 'connected' && scoreId !== null ? (
            <QuestionPanel api={engine.api} scoreId={scoreId} onAnswered={refreshInfo} />
          ) : (
            reading === null && <p className="empty">{t('panels.questionsEmpty')}</p>
          )}
        </section>
        <section className="panel" aria-labelledby="panel-result">
          <h2 id="panel-result">{t('panels.result')}</h2>
          <p className="empty">{t('panels.resultEmpty')}</p>
        </section>
      </main>

      <footer className="status-bar" role="status">
        {engine.kind === 'connecting' && t('status.connecting')}
        {engine.kind === 'unavailable' && t('status.noBridge')}
        {engine.kind === 'connected' && (
          <>
            {t('status.connected', {
              version: engine.info.version,
              python: engine.info.python_version,
            })}
            {' · '}
            {t('status.corrections', { count: engine.info.correction_count })}
          </>
        )}
      </footer>
    </div>
  )
}
