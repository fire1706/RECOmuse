// Écran principal de RECOmuse, à la manière de MuseScore 4 :
// - onglet Accueil : les partitions déjà lues, en cartes groupées par morceau, et une carte
//   pour en ouvrir une nouvelle ;
// - onglet Partition : barre d'outils, puis les questions (panneau de gauche, repliable),
//   le scan d'origine (repliable) et la partition reconnue, côte à côte. Une mesure choisie
//   (clic sur le scan, sur le rendu, question en cours ou passage à vérifier) est montrée
//   des deux côtés.

import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  type AppInfo,
  isError,
  type PythonApi,
  type ReadingState,
  type ScoreSummary,
  waitForBridge,
} from './bridge'
import Dock from './Dock'
import { SUPPORTED_LANGUAGES } from './i18n'
import {
  ConductorIcon,
  ExportIcon,
  NoteIcon,
  OpenIcon,
  PacksIcon,
  RulesIcon,
  TransposeIcon,
} from './Icons'
import MeasureEditor from './MeasureEditor'
import PacksDialog from './PacksDialog'
import QuestionPanel from './QuestionPanel'
import ReadingProgress from './ReadingProgress'
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

// État affiché dès le clic, avant la première réponse du moteur.
const READING_START: ReadingState = {
  stage: 'import',
  page: null,
  pages: null,
  fraction: 0,
  elapsed: 0,
  cancelling: false,
}

/** Onglets de la barre du haut. */
type Tab = 'home' | 'score'

/** Panneaux repliables de l'onglet Partition : ouverts ou repliés. */
interface DockState {
  questions: boolean
  scan: boolean
}

// Les panneaux repliés sont retenus d'une fois sur l'autre (dans le navigateur intégré).
const DOCKS_KEY = 'recomuse.docks'
const DOCKS_DEFAULT: DockState = { questions: true, scan: true }

function loadDocks(): DockState {
  try {
    const saved = window.localStorage.getItem(DOCKS_KEY)
    return saved ? { ...DOCKS_DEFAULT, ...JSON.parse(saved) } : DOCKS_DEFAULT
  } catch {
    return DOCKS_DEFAULT
  }
}

function saveDocks(docks: DockState) {
  try {
    window.localStorage.setItem(DOCKS_KEY, JSON.stringify(docks))
  } catch {
    // Pas de mémoire disponible : les panneaux reviendront ouverts, sans plus.
  }
}

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
  const [tab, setTab] = useState<Tab>('home')
  const [docks, setDocks] = useState<DockState>(loadDocks)
  const [scores, setScores] = useState<ScoreSummary[]>([])
  const [scoreId, setScoreId] = useState<number | null>(null)
  // Lecture en cours (étape, page, part faite...) ; null : aucune lecture.
  const [reading, setReading] = useState<ReadingState | null>(null)
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

  /** Replie ou rouvre un panneau, et le retient. */
  function toggleDock(name: keyof DockState) {
    const next = { ...docks, [name]: !docks[name] }
    setDocks(next)
    saveDocks(next)
  }

  /** Choisit une partition (l'onglet Partition s'ouvre) : sa première page, aucune
   *  mesure choisie. */
  const chooseScore = useCallback((id: number | null, known: ScoreSummary[]) => {
    if (id !== null) setTab('score')
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
    setTab('score')
    setReading(READING_START)
    poll.current = window.setInterval(async () => {
      const state = await api.get_progress()
      if (state.stage !== null) setReading(state)
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
  const busy = !connected || reading !== null

  /** Messages après une lecture : parties trouvées, corrections reprises, erreur. */
  const notices = (
    <div className="notices">
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
        // Une lecture annulée n'est pas une erreur : simple remarque.
        <p className={openError === 'cancelled' ? 'question-note' : 'error'}>
          {t(`errors.${openError}`, { defaultValue: t('errors.unexpected') })}
        </p>
      )}
    </div>
  )

  return (
    <div className="app">
      <header className="topbar">
        <h1 className="brand">
          <NoteIcon />
          {t('app.title')}
        </h1>
        <nav className="tabs" role="tablist" aria-label={t('tabs.label')}>
          {(['home', 'score'] as const).map((name) => (
            <button key={name} type="button" role="tab" className="tab"
              aria-selected={tab === name} onClick={() => setTab(name)}>
              {t(`tabs.${name}`)}
            </button>
          ))}
        </nav>
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
      </header>

      {tab === 'home' && (
        <main className="home">
          <h2>{t('home.title')}</h2>
          <p className="home-tagline">{t('app.tagline')}</p>
          {notices}
          <div className="cards">
            <button type="button" className="card card-new" onClick={openScore} disabled={busy}
              aria-label={t('open.button')}>
              <span className="card-sheet">
                <OpenIcon />
              </span>
              <span className="card-name">{t('open.button')}</span>
              <span className="card-detail">{t('home.formats')}</span>
            </button>
          </div>
          {scores.length === 0 && connected && <p className="empty">{t('home.empty')}</p>}
          {groupByPiece(scores, t('scores.unknownPiece')).map(([title, parts]) => (
            <section key={title} className="home-piece" aria-label={title}>
              <h3>{title}</h3>
              <div className="cards">
                {parts.map((score) => (
                  <button key={score.score_id} type="button" className="card" disabled={busy}
                    onClick={() => chooseScore(score.score_id, scores)}>
                    <span className="card-sheet">
                      <NoteIcon />
                    </span>
                    <span className="card-name">{scoreLabel(score, t('scores.untitled'))}</span>
                    <span className="card-detail">
                      {t('home.measures', { count: score.measure_count })}
                    </span>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </main>
      )}

      {tab === 'score' && (
        <>
          <div className="toolbar" role="toolbar" aria-label={t('toolbar.label')}>
            <button type="button" className="tool" onClick={openScore} disabled={busy}>
              <OpenIcon />
              {t('open.button')}
            </button>
            <button type="button" className="tool" onClick={() => setExporting(true)}
              disabled={busy || scoreId === null}>
              <ExportIcon />
              {t('export.button')}
            </button>
            <span className="toolbar-separator" />
            <button type="button" className="tool" onClick={() => setTransposing(true)}
              disabled={busy || scoreId === null}>
              <TransposeIcon />
              {t('transpose.button')}
            </button>
            <button type="button" className="tool" onClick={() => setShowConductor(true)}
              disabled={busy || scoreId === null}>
              <ConductorIcon />
              {t('conductor.button')}
            </button>
            <span className="toolbar-separator" />
            <button type="button" className="tool" onClick={() => setShowRules(true)}
              disabled={!connected}>
              <RulesIcon />
              {t('rules.button')}
            </button>
            <button type="button" className="tool" onClick={() => setShowPacks(true)}
              disabled={!connected}>
              <PacksIcon />
              {t('packs.button')}
            </button>
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
          </div>

          <main className="workspace">
            <Dock id="questions" title={t('panels.questions')} open={docks.questions}
              onToggle={() => toggleDock('questions')}>
              {notices}
              {reading === null && engine.kind === 'connected' && scoreId !== null ? (
                <QuestionPanel key={`${scoreId}-${editVersion}`} api={engine.api} scoreId={scoreId}
                  onAnswered={refreshInfo} onFocus={focusMeasure} />
              ) : (
                reading === null && <p className="empty">{t('panels.questionsEmpty')}</p>
              )}
            </Dock>

            <Dock id="scan" title={t('panels.scan')} open={docks.scan}
              onToggle={() => toggleDock('scan')}>
              {engine.kind === 'connected' && scoreId !== null && page !== null && reading === null ? (
                <ScanView api={engine.api} scoreId={scoreId} page={page} version={version}
                  selectedMeasure={selected} onPage={setPage} onSelect={focusMeasure} />
              ) : (
                <p className="empty">
                  {current?.derived === 'assembled' ? t('conductor.noPages') : t('panels.scanEmpty')}
                </p>
              )}
            </Dock>

            <section className="canvas" aria-labelledby="result-title">
              <div className="dock-header">
                <h2 id="result-title">{t('panels.result')}</h2>
              </div>
              <div className="canvas-body">
                {reading !== null && engine.kind === 'connected' && (
                  <ReadingProgress
                    state={reading}
                    onCancel={() => {
                      setReading({ ...reading, cancelling: true })
                      void engine.api.cancel_reading()
                    }}
                  />
                )}
                {engine.kind === 'connected' && scoreId !== null && reading === null && selected !== null && (
                  <MeasureEditor api={engine.api} scoreId={scoreId} measureId={selected} symbolId={symbol}
                    version={version} onSelectSymbol={setSymbol}
                    onSelectMeasure={(id) => focusMeasure(id, null)} onEdited={afterEdit} />
                )}
                {engine.kind === 'connected' && scoreId !== null && reading === null ? (
                  <div className="sheet">
                    <ScoreView api={engine.api} scoreId={scoreId} version={version}
                      selectedMeasure={selected} selectedSymbol={symbol} onSelect={focusMeasure} />
                  </div>
                ) : (
                  reading === null && <p className="empty">{t('panels.resultEmpty')}</p>
                )}
              </div>
            </section>
          </main>
        </>
      )}

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
