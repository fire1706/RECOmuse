// Éditeur de la mesure choisie : ses réglages (clé, armure, chiffrage, tempo, pause
// multiple), ses notes et silences, et les gestes possibles sur le symbole choisi (dont
// les signes d'expression : articulations, nuance, liaison, soufflet). La mesure peut être
// réunie à la suivante (barre en trop) ou coupée après la note choisie (barre manquée).
// Chaque geste est une correction « manuelle » enregistrée par le moteur ; « Annuler ma
// dernière modification » la défait. Raccourcis quand une note est choisie : flèches
// haut et bas (un cran), Suppr (supprimer).

import { useEffect, useRef, useState } from 'react'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'

import { type Edit, isError, type MeasureDetails, type MeasureSymbol, type PythonApi } from './bridge'
import type { Language } from './i18n'
import { noteName } from './music'

interface MeasureEditorProps {
  api: PythonApi
  scoreId: number
  measureId: string
  symbolId: string | null
  /** Change à chaque correction (réponse à une question, autre geste) : la mesure est relue. */
  version: number
  onSelectSymbol: (symbolId: string | null) => void
  onSelectMeasure: (measureId: string) => void
  /** Après un geste : la partition a changé, la mesure et le symbole à montrer. */
  onEdited: (measureId: string | null, symbolId: string | null) => void
}

/** Durées écrites proposées (en noires) et leur nom dans les traductions. */
export const DURATIONS: [string, string][] = [
  ['4', 'whole'], ['2', 'half'], ['1', 'quarter'], ['1/2', 'eighth'], ['1/4', 'sixteenth'], ['1/8', 'thirtySecond'],
]

/** Signes d'expression proposés (noms du moteur : src/recomuse/model/marks.py). */
export const ARTICULATIONS = ['staccato', 'accent', 'tenuto', 'marcato', 'fermata']
export const DYNAMICS = ['ppp', 'pp', 'p', 'mp', 'mf', 'f', 'ff', 'fff', 'sfz', 'fp']

/** Clés proposées : signe, ligne, octave (« G:2:-1 » = clé de sol 8 en dessous). */
export const CLEFS: [string, string][] = [
  ['G:2:0', 'treble'], ['G:2:-1', 'treble8'], ['F:4:0', 'bass'], ['C:3:0', 'alto'], ['C:4:0', 'tenor'],
  ['percussion::0', 'percussion'],
]

function clefKey(clef: MeasureDetails['state']['clef']): string {
  return `${clef.sign}:${clef.line ?? ''}:${clef.octave_change ?? 0}`
}

/** Nom court d'un symbole (« do5, noire pointée », « silence, croche »). */
export function symbolLabel(symbol: MeasureSymbol, t: TFunction, language: Language) {
  const value = symbol.value
  const duration = DURATIONS.find(([written]) => written === value.written)?.[1]
  const length = duration ? t(`editor.durations.${duration}`) : '?'
  const dots = Number(value.dots ?? 0)
  const dotted = dots > 0 ? ` ${t('editor.dotted', { count: dots })}` : ''
  const tuplet = value.tuplet ? ` ${t('editor.tuplet')}` : ''
  if (symbol.kind === 'note') {
    const name = typeof value.step === 'string' && typeof value.octave === 'number'
      ? noteName({ step: value.step, octave: value.octave, alter: Number(value.alter ?? 0) }, language)
      : t('editor.percussionNote')
    return `${name}, ${length}${dotted}${tuplet}`
  }
  if (value.full_measure) return t('editor.fullRest')
  return `${t('editor.rest')}, ${length}${dotted}${tuplet}`
}

export default function MeasureEditor({
  api, scoreId, measureId, symbolId, version, onSelectSymbol, onSelectMeasure, onEdited,
}: MeasureEditorProps) {
  const { t, i18n } = useTranslation()
  const language = (i18n.resolvedLanguage ?? 'fr') as Language
  const [details, setDetails] = useState<MeasureDetails | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [beats, setBeats] = useState('')
  const [beatType, setBeatType] = useState('')
  const [count, setCount] = useState('')
  const [tempoText, setTempoText] = useState('')
  const [tempoSpeed, setTempoSpeed] = useState('')

  useEffect(() => {
    let cancelled = false
    api
      .get_measure(scoreId, measureId)
      .then((result) => {
        if (cancelled) return
        if (isError(result)) {
          setError(result.error)
          return
        }
        setError(null)
        setDetails(result)
        const [b, bt] = (result.state.time ?? '/').split('/')
        setBeats(b)
        setBeatType(bt)
        setCount(String(result.length))
        const tempo = result.attributes.find((s) => s.kind === 'tempo')
        setTempoText(String(tempo?.value.text ?? ''))
        setTempoSpeed(tempo?.value.per_minute ? String(tempo.value.per_minute) : '')
      })
      .catch(() => !cancelled && setError('unexpected'))
    return () => {
      cancelled = true
    }
  }, [api, scoreId, measureId, version])

  /** Envoie un geste au moteur. */
  async function edit(gesture: Edit) {
    setBusy(true)
    setError(null)
    try {
      const result = await api.edit_score(scoreId, gesture)
      if (isError(result)) setError(result.error)
      else onEdited(result.measure_id ?? measureId, result.symbol_id)
    } catch {
      setError('unexpected')
    } finally {
      setBusy(false)
    }
  }

  async function undo() {
    setBusy(true)
    setError(null)
    try {
      const result = await api.undo_edit(scoreId)
      if (isError(result)) setError(result.error)
      else onEdited(result.measure_id, null)
    } catch {
      setError('unexpected')
    } finally {
      setBusy(false)
    }
  }

  const selected = details?.events.find((s) => s.id === symbolId) ?? null

  // Raccourcis clavier sur la note choisie (sauf pendant la saisie d'un nombre).
  const keys = useRef<(event: KeyboardEvent) => void>(() => {})
  keys.current = (event: KeyboardEvent) => {
    const target = event.target instanceof Element ? event.target : null
    if (!selected || busy || target?.closest('input, select, textarea')) return
    if (selected.kind === 'note' && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
      event.preventDefault()
      edit({ op: 'pitch', symbol_id: selected.id, steps: event.key === 'ArrowUp' ? 1 : -1 })
    } else if (event.key === 'Delete') {
      event.preventDefault()
      edit({ op: 'remove', symbol_id: selected.id })
    }
  }
  useEffect(() => {
    const listener = (event: KeyboardEvent) => keys.current(event)
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [])

  if (error && !details) {
    return <p className="error">{t(`errors.${error}`, { defaultValue: t('errors.unexpected') })}</p>
  }
  if (!details || details.id !== measureId) return <p className="empty">{t('editor.loading')}</p>

  const wrongLength = details.duration !== null && details.expected !== null && details.length === 1
    && details.events.length > 0
    && details.duration !== details.expected && !details.events.some((e) => e.value.full_measure)
  const written = selected ? String(selected.value.written ?? '') : ''
  const dots = selected ? Number(selected.value.dots ?? 0) : 0

  return (
    <div className="measure-editor">
      <div className="editor-header">
        <button type="button" className="link-button" disabled={!details.previous}
          onClick={() => details.previous && onSelectMeasure(details.previous)}>
          {t('editor.previous')}
        </button>
        <strong>{t('editor.measure', { number: details.number })}</strong>
        <button type="button" className="link-button" disabled={!details.next}
          onClick={() => details.next && onSelectMeasure(details.next)}>
          {t('editor.next')}
        </button>
        {details.can_undo && (
          <button type="button" className="link-button" disabled={busy} onClick={undo}>
            {t('editor.undo')}
          </button>
        )}
      </div>
      {wrongLength && (
        <p className="question-note">{t('editor.wrongLength', { read: details.duration, expected: details.expected })}</p>
      )}

      <div className="editor-row">
        <label>
          {t('editor.clef')}
          <select value={clefKey(details.state.clef)} disabled={busy}
            onChange={(e) => {
              const [sign, line, octave] = e.target.value.split(':')
              edit({ op: 'clef', measure_id: details.id, sign, line: Number(line || 0), octave_change: Number(octave) })
            }}>
            {!CLEFS.some(([key]) => key === clefKey(details.state.clef)) && (
              <option value={clefKey(details.state.clef)}>{t('editor.clefs.other')}</option>
            )}
            {CLEFS.map(([key, name]) => (
              <option key={key} value={key}>{t(`editor.clefs.${name}`)}</option>
            ))}
          </select>
        </label>
        <label>
          {t('editor.key')}
          <select value={details.state.fifths} disabled={busy}
            onChange={(e) => edit({ op: 'key', measure_id: details.id, fifths: Number(e.target.value) })}>
            {Array.from({ length: 15 }, (_, k) => 7 - k).map((fifths) => (
              <option key={fifths} value={fifths}>
                {fifths === 0 ? t('editor.noAccidental')
                  : fifths > 0 ? t('editor.sharps', { count: fifths }) : t('editor.flats', { count: -fifths })}
              </option>
            ))}
          </select>
        </label>
        <form className="inline-form"
          onSubmit={(e) => {
            e.preventDefault()
            edit({ op: 'time', measure_id: details.id, beats: Number(beats), beat_type: Number(beatType) })
          }}>
          <label>
            {t('editor.time')}
            <input type="number" min={1} max={32} value={beats} aria-label={t('editor.beats')}
              onChange={(e) => setBeats(e.target.value)} disabled={busy} />
          </label>
          /
          <input type="number" min={1} max={32} value={beatType} aria-label={t('editor.beatType')}
            onChange={(e) => setBeatType(e.target.value)} disabled={busy} />
          <button type="submit" disabled={busy}>{t('editor.apply')}</button>
        </form>
        <form className="inline-form"
          onSubmit={(e) => {
            e.preventDefault()
            edit({ op: 'tempo', measure_id: details.id, text: tempoText, per_minute: tempoSpeed })
          }}>
          <label>
            {t('editor.tempo')}
            <input value={tempoText} placeholder={t('editor.tempoText')} disabled={busy}
              aria-label={t('editor.tempoText')} onChange={(e) => setTempoText(e.target.value)} />
          </label>
          <label>
            ♩ =
            <input type="number" min={20} max={400} value={tempoSpeed} disabled={busy}
              aria-label={t('editor.tempoSpeed')} onChange={(e) => setTempoSpeed(e.target.value)} />
          </label>
          <button type="submit" disabled={busy}>{t('editor.apply')}</button>
        </form>
        <form className="inline-form"
          onSubmit={(e) => {
            e.preventDefault()
            edit({ op: 'multirest', measure_id: details.id, count: Number(count) })
          }}>
          <label>
            {t('editor.restLength')}
            <input type="number" min={1} value={count} onChange={(e) => setCount(e.target.value)} disabled={busy} />
          </label>
          <button type="submit" disabled={busy}>{t('editor.apply')}</button>
        </form>
      </div>

      <div className="editor-row symbols">
        {details.events.map((symbol) => (
          <button key={symbol.id} type="button" disabled={busy}
            className={`symbol-chip${symbol.id === symbolId ? ' selected' : ''}${symbol.confidence < 0.7 ? ' doubtful' : ''}`}
            aria-pressed={symbol.id === symbolId}
            onClick={() => onSelectSymbol(symbol.id === symbolId ? null : symbol.id)}>
            {symbolLabel(symbol, t, language)}
          </button>
        ))}
        {details.events.length === 0 && <span className="empty">{t('editor.emptyMeasure')}</span>}
        {details.next && (
          <button type="button" className="link-button" disabled={busy}
            onClick={() => edit({ op: 'merge_next', measure_id: details.id })}>
            {t('editor.mergeNext')}
          </button>
        )}
        {!selected && details.length === 1 && (
          <>
            <button type="button" className="link-button" disabled={busy}
              onClick={() => edit({ op: 'add_note', measure_id: details.id })}>
              {t('editor.addNoteStart')}
            </button>
            <button type="button" className="link-button" disabled={busy}
              onClick={() => edit({ op: 'add_rest', measure_id: details.id })}>
              {t('editor.addRestStart')}
            </button>
          </>
        )}
      </div>

      {selected && (
        <div className="symbol-editor">
          {selected.kind === 'note' && (
            <div className="editor-row">
              <span className="editor-label">{t('editor.pitch')}</span>
              <button type="button" disabled={busy} onClick={() => edit({ op: 'pitch', symbol_id: selected.id, steps: 1 })}>
                {t('editor.up')}
              </button>
              <button type="button" disabled={busy} onClick={() => edit({ op: 'pitch', symbol_id: selected.id, steps: -1 })}>
                {t('editor.down')}
              </button>
              <button type="button" disabled={busy} onClick={() => edit({ op: 'octave', symbol_id: selected.id, change: 1 })}>
                {t('editor.octaveUp')}
              </button>
              <button type="button" disabled={busy} onClick={() => edit({ op: 'octave', symbol_id: selected.id, change: -1 })}>
                {t('editor.octaveDown')}
              </button>
              {[-1, 0, 1].map((alter) => (
                <button key={alter} type="button" disabled={busy}
                  aria-pressed={Number(selected.value.alter ?? 0) === alter}
                  onClick={() => edit({ op: 'alter', symbol_id: selected.id, alter })}>
                  {t(`editor.alter.${alter === -1 ? 'flat' : alter === 1 ? 'sharp' : 'natural'}`)}
                </button>
              ))}
            </div>
          )}
          <div className="editor-row">
            <span className="editor-label">{t('editor.duration')}</span>
            {DURATIONS.map(([value, name]) => (
              <button key={value} type="button" disabled={busy} aria-pressed={written === value}
                onClick={() => edit({ op: 'duration', symbol_id: selected.id, written: value, dots })}>
                {t(`editor.durations.${name}`)}
              </button>
            ))}
            {[0, 1, 2].map((n) => (
              <button key={n} type="button" disabled={busy || !written} aria-pressed={dots === n}
                onClick={() => edit({ op: 'duration', symbol_id: selected.id, written, dots: n })}>
                {t('editor.dots', { count: n })}
              </button>
            ))}
          </div>
          <div className="editor-row">
            {selected.kind === 'note' && (
              <button type="button" disabled={busy} aria-pressed={Boolean(selected.value.tie_start)}
                onClick={() => edit({ op: 'tie', symbol_id: selected.id })}>
                {t('editor.tie')}
              </button>
            )}
            <button type="button" disabled={busy}
              onClick={() => edit({ op: 'add_note', measure_id: details.id, after: selected.id })}>
              {t('editor.addNote')}
            </button>
            <button type="button" disabled={busy}
              onClick={() => edit({ op: 'add_rest', measure_id: details.id, after: selected.id })}>
              {t('editor.addRest')}
            </button>
            <button type="button" disabled={busy || selected.id === details.events.at(-1)?.id}
              onClick={() => edit({ op: 'split_after', symbol_id: selected.id })}>
              {t('editor.splitAfter')}
            </button>
            <button type="button" className="danger" disabled={busy}
              onClick={() => edit({ op: 'remove', symbol_id: selected.id })}>
              {t('editor.remove')}
            </button>
          </div>
          <div className="editor-row">
            <span className="editor-label">{t('editor.expression')}</span>
            {ARTICULATIONS.filter((name) => selected.kind === 'note' || name === 'fermata').map((name) => (
              <button key={name} type="button" disabled={busy}
                aria-pressed={((selected.value.articulations as string[] | undefined) ?? []).includes(name)}
                onClick={() => edit({ op: 'articulation', symbol_id: selected.id, name })}>
                {t(`editor.articulations.${name}`)}
              </button>
            ))}
            <label>
              {t('editor.dynamic')}
              <select value={String(selected.value.dynamic ?? '')} disabled={busy}
                onChange={(e) => edit({ op: 'dynamic', symbol_id: selected.id, value: e.target.value })}>
                <option value="">—</option>
                {DYNAMICS.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            </label>
          </div>
          <div className="editor-row">
            {selected.kind === 'note' && (['start', 'stop'] as const).map((end) => (
              <button key={end} type="button" disabled={busy}
                aria-pressed={Boolean(selected.value[end === 'start' ? 'slur_start' : 'slur_stop'])}
                onClick={() => edit({ op: 'slur', symbol_id: selected.id, end })}>
                {t(`editor.slur.${end}`)}
              </button>
            ))}
            <label>
              {t('editor.wedge')}
              <select value={String(selected.value.wedge_start ?? 'none')} disabled={busy}
                onChange={(e) => edit({ op: 'wedge', symbol_id: selected.id, value: e.target.value })}>
                <option value="none">—</option>
                <option value="crescendo">{t('editor.wedges.crescendo')}</option>
                <option value="diminuendo">{t('editor.wedges.diminuendo')}</option>
              </select>
            </label>
            <button type="button" disabled={busy} aria-pressed={Boolean(selected.value.wedge_stop)}
              onClick={() => edit({ op: 'wedge', symbol_id: selected.id, value: selected.value.wedge_stop ? 'none' : 'stop' })}>
              {t('editor.wedgeStop')}
            </button>
          </div>
        </div>
      )}
      {error && <p className="error">{t(`errors.${error}`, { defaultValue: t('errors.unexpected') })}</p>}
    </div>
  )
}
