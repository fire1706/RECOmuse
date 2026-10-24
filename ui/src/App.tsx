// Écran principal de RECOmuse.
//
// Disposition prévue par le cahier des charges :
//   à gauche le scan d'origine, au centre les questions, à droite le rendu Verovio.
// Tâche 8 : ouverture d'une partition et questions guidées (zone du centre).
// Tâche 9 : vue côte à côte. Une mesure choisie (clic sur le scan, sur le rendu, question
// en cours ou passage à vérifier) est montrée des deux côtés.

import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { type AppInfo, isError, type PythonApi, type ScoreSummary, waitForBridge } from './bridge'
import { SUPPORTED_LANGUAGES } from './i18n'
import MeasureEditor from './MeasureEditor'
import PacksDialog from './PacksDialog'
import QuestionPanel from './QuestionPanel'
import RulesDialog from './RulesDialog'
import ScanView from './ScanView'
import ScoreView from './ScoreView'
import ConductorDialog from './ConductorDialog'
import ExportDialog from './ExportDialog'
import TransposeDialog from './TransposeDialog'
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
  // Parties déjà lues et corrigées : ce qui a été repris à l'ouverture.
  const [remembered, setRemembered] = useState<ScoreSummary[]>([])
  // Vue côte à côte : page montrée à gauche, mesure choisie, et un compteur qui change à
  // chaque correction (les deux vues se redessinent alors).
  const [page, setPage] = useState<number | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [symbol, setSymbol] = useState<string | null>(null)
  const [version, setVersion] = useState(0)
  // Change après une modification manuelle : les questions sont recalculées.
  const [editVersion, setEditVersion] = useState(0)
  const [transposing, setTransposing] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [showRules, setShowRules] = useState(false)
  const [showPacks, setShowPacks] = useState(false)
  const [showConductor, setShowConductor] = useState(false)
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

  /** Après une correction : relit le nombre de corrections, redessine les deux vues. */
  const refreshInfo = useCallback(async () => {
    setVersion((v) => v + 1)
    if (engine.kind !== 'connected') return
    const info = await engine.api.get_app_info()
    setEngine({ ...engine, info })
    // Le nombre de mesures d'une partition a pu changer (pause multiple corrigée).
    setScores(await engine.api.list_scores())
  }, [engine])

  /** Choisit une partition : sa première page, aucune mesure choisie. */
  const chooseScore = useCallback((id: number | null, known: ScoreSummary[]) => {
    setScoreId(id)
    setSelected(null)
    setSymbol(null)
    setPage(known.find((s) => s.score_id === id)?.pages[0] ?? null)
  }, [])

  /** Montre une mesure des deux côtés (et sa page à gauche), et choisit un symbole. */
  const focusMeasure = useCallback(
    (measureId: string | null, measurePage: number | null, symbolId: string | null = null) => {
      setSelected(measureId)
      setSymbol(symbolId)
      if (measurePage !== null) setPage(measurePage)
    },
    [],
  )

  /** Après une modification manuelle : tout est redessiné, les questions recalculées. */
  const afterEdit = useCallback(
    (measureId: string | null, symbolId: string | null) => {
      if (measureId) setSelected(measureId)
      setSymbol(symbolId)
      setEditVersion((v) => v + 1)
      refreshInfo()
    },
    [refreshInfo],
  )

  async function openScore() {
    if (engine.kind !== 'connected') return
    const { api } = engine
    let path: string | null
    try {
      path = await api.choose_file(t('open.filter'))
    } catch {
      // La fenêtre « Ouvrir » n'a pas pu s'ouvrir : le dire, plutôt que ne rien faire.
      setOpenError('dialog_failed')
      return
    }
    if (!path) return
    setOpenError(null)
    setOpenedParts(null)
    setRemembered([])
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
        const known = [...result.scores, ...scores]
        setScores(known)
        chooseScore(result.scores[0]?.score_id ?? null, known)
        setOpenedParts(result.scores.length)
        setRemembered(result.scores.filter((s) => s.memory))
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
  const current = scores.find((s) => s.score_id === scoreId) ?? null

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
          {scoreId !== null && (
            <button type="button" onClick={() => setTransposing(true)} disabled={!connected || reading !== null}>
              {t('transpose.button')}
            </button>
          )}
          {scoreId !== null && (
            <button type="button" onClick={() => setShowConductor(true)} disabled={!connected || reading !== null}>
              {t('conductor.button')}
            </button>
          )}
          {scoreId !== null && (
            <button type="button" onClick={() => setExporting(true)} disabled={!connected || reading !== null}>
              {t('export.button')}
            </button>
          )}
          {scores.length > 0 && (
            <label className="score-picker">
              {t('scores.label')}
              <select value={scoreId ?? ''} disabled={reading !== null}
                onChange={(e) => chooseScore(e.target.value ? Number(e.target.value) : null, scores)}>
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
          {connected && (
            <button type="button" onClick={() => setShowRules(true)}>
              {t('rules.button')}
            </button>
          )}
          {connected && (
            <button type="button" onClick={() => setShowPacks(true)}>
              {t('packs.button')}
            </button>
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
          {engine.kind === 'connected' && scoreId !== null && page !== null && reading === null ? (
            <ScanView api={engine.api} scoreId={scoreId} page={page} version={version}
              selectedMeasure={selected} onPage={setPage} onSelect={focusMeasure} />
          ) : (
            <p className="empty">
              {current?.derived === 'assembled' ? t('conductor.noPages') : t('panels.scanEmpty')}
            </p>
          )}
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
          {remembered.map((score) => (
            <p key={score.score_id} className="question-note">
              {t(score.memory!.from_pack ? 'memory.fromPack' : 'memory.replayed', {
                name: score.instrument ?? score.title ?? '',
                author: score.memory!.author ?? t('packs.anonymous'),
                date: new Date(score.memory!.read_at).toLocaleDateString(i18n.resolvedLanguage),
                corrections: t('memory.corrections', { count: score.memory!.applied }),
                answers: t('memory.answers', { count: score.memory!.answers }),
              })}
              {score.memory!.skipped > 0 && ` ${t('memory.skipped', { count: score.memory!.skipped })}`}
            </p>
          ))}
          {openError && (
            <p className="error">{t(`errors.${openError}`, { defaultValue: t('errors.unexpected') })}</p>
          )}
          {reading === null && engine.kind === 'connected' && scoreId !== null ? (
            <QuestionPanel key={`${scoreId}-${editVersion}`} api={engine.api} scoreId={scoreId}
              onAnswered={refreshInfo} onFocus={focusMeasure} />
          ) : (
            reading === null && <p className="empty">{t('panels.questionsEmpty')}</p>
          )}
        </section>
        <section className="panel" aria-labelledby="panel-result">
          <h2 id="panel-result">{t('panels.result')}</h2>
          {engine.kind === 'connected' && scoreId !== null && reading === null && selected !== null && (
            <MeasureEditor api={engine.api} scoreId={scoreId} measureId={selected} symbolId={symbol}
              version={version} onSelectSymbol={setSymbol}
              onSelectMeasure={(id) => focusMeasure(id, null)} onEdited={afterEdit} />
          )}
          {engine.kind === 'connected' && scoreId !== null && reading === null ? (
            <ScoreView api={engine.api} scoreId={scoreId} version={version}
              selectedMeasure={selected} selectedSymbol={symbol} onSelect={focusMeasure} />
          ) : (
            <p className="empty">{t('panels.resultEmpty')}</p>
          )}
        </section>
      </main>

      {transposing && engine.kind === 'connected' && scoreId !== null && (
        <TransposeDialog api={engine.api} scoreId={scoreId} onClose={() => setTransposing(false)}
          onCreated={(score) => {
            const known = [score, ...scores]
            setScores(known)
            setTransposing(false)
            chooseScore(score.score_id, known)
          }} />
      )}

      {exporting && engine.kind === 'connected' && scoreId !== null && (
        <ExportDialog api={engine.api} scoreId={scoreId} onClose={() => setExporting(false)} />
      )}

      {showConductor && engine.kind === 'connected' && current && (
        <ConductorDialog api={engine.api} score={current} onClose={() => setShowConductor(false)}
          onCreated={(created) => {
            const known = [...created, ...scores]
            setScores(known)
            setShowConductor(false)
            chooseScore(created[0]?.score_id ?? null, known)
          }} />
      )}

      {showPacks && engine.kind === 'connected' && (
        <PacksDialog api={engine.api} onClose={() => setShowPacks(false)} />
      )}

      {showRules && engine.kind === 'connected' && (
        <RulesDialog api={engine.api} onClose={() => setShowRules(false)} />
      )}

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
