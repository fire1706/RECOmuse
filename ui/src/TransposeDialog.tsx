// Fenêtre « Transposer » : réécrire la partie pour un autre instrument (ou d'un intervalle).
// On choisit d'abord l'instrument de la partie (reconnu d'après son nom, corrigeable), puis
// le nouvel instrument ; l'aperçu dit l'armure obtenue et combien de notes sortiraient de
// l'étendue, et conseille une octave. La partie transposée est une NOUVELLE partition :
// celle d'origine ne change pas.

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  type InstrumentInfo,
  isError,
  type PythonApi,
  type ScoreSummary,
  type TranspositionReport,
  type TranspositionRequest,
} from './bridge'
import type { Language } from './i18n'

interface TransposeDialogProps {
  api: PythonApi
  scoreId: number
  onCreated: (score: ScoreSummary) => void
  onClose: () => void
}

/** Intervalles proposés (notation du moteur : M2 = seconde majeure, P8 = octave). */
export const INTERVALS = ['m2', 'M2', 'm3', 'M3', 'P4', 'P5', 'm6', 'M6', 'P8']
const OCTAVES = [-2, -1, 0, 1, 2]
/** Clé d'une version d'instrument → nom de clé dans les traductions (transpose.clefs). */
const CLEF_NAMES: Record<string, string> = { G2: 'treble', F4: 'bass', C3: 'alto', C4: 'tenor', perc: 'percussion' }

type Translate = ReturnType<typeof useTranslation>['t']

/** Nom d'une version : « en si♭, clé de sol ». */
export function variantLabel(variant: InstrumentInfo['variants'][number], t: Translate): string {
  const clef = t(`transpose.clefs.${CLEF_NAMES[variant.clef] ?? 'other'}`)
  return variant.key ? t('transpose.version', { key: t(`transpose.keys.${variant.key}`), clef }) : clef
}

/** Armure en mots : « 2 dièses », « aucune altération ». */
function keyText(fifths: number, t: Translate): string {
  if (fifths === 0) return t('editor.noAccidental')
  return fifths > 0 ? t('editor.sharps', { count: fifths }) : t('editor.flats', { count: -fifths })
}

export default function TransposeDialog({ api, scoreId, onCreated, onClose }: TransposeDialogProps) {
  const { t, i18n } = useTranslation()
  const language = (i18n.resolvedLanguage ?? 'fr') as Language
  const [table, setTable] = useState<InstrumentInfo[]>([])
  const [source, setSource] = useState<{ instrument: string; variant: string } | null>(null)
  const [detected, setDetected] = useState(false)
  const [mode, setMode] = useState<'instrument' | 'interval'>('instrument')
  const [target, setTarget] = useState<{ instrument: string; variant: string } | null>(null)
  const [interval, setIntervalName] = useState('M2')
  const [direction, setDirection] = useState<'up' | 'down'>('up')
  const [octave, setOctave] = useState(0)
  const [report, setReport] = useState<TranspositionReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const label = (id: string | undefined) => {
    const instrument = table.find((i) => i.id === id)
    return instrument ? (instrument.label[language] ?? instrument.label.fr ?? instrument.id) : ''
  }
  const variantsOf = (id: string | undefined) =>
    (table.find((i) => i.id === id)?.variants ?? []).filter((v) => v.transposable)

  // La table des instruments et l'instrument de la partie.
  useEffect(() => {
    let cancelled = false
    Promise.all([api.get_instruments(), api.get_score_instrument(scoreId)])
      .then(([instruments, current]) => {
        if (cancelled) return
        setTable(instruments)
        if (!isError(current) && current.instrument_id && current.variant_id) {
          setSource({ instrument: current.instrument_id, variant: current.variant_id })
          setDetected(current.detected)
        }
      })
      .catch(() => !cancelled && setError('unexpected'))
    return () => {
      cancelled = true
    }
  }, [api, scoreId])

  const request: TranspositionRequest | null =
    mode === 'interval'
      ? { mode, interval, direction, octave }
      : target && source
        ? { mode, target, octave }
        : null

  // Aperçu, à chaque changement de la demande.
  const requestKey = JSON.stringify(request)
  useEffect(() => {
    if (!request) {
      setReport(null)
      return
    }
    let cancelled = false
    api
      .check_transposition(scoreId, request)
      .then((result) => {
        if (cancelled) return
        if (isError(result)) {
          setError(result.error)
          setReport(null)
        } else {
          setError(null)
          setReport(result)
        }
      })
      .catch(() => !cancelled && setError('unexpected'))
    return () => {
      cancelled = true
    }
    // requestKey résume la demande : `request` est un objet neuf à chaque affichage.
  }, [api, scoreId, requestKey])

  async function chooseSource(instrument: string, variant: string) {
    setSource({ instrument, variant })
    setDetected(false)
    const result = await api.set_score_instrument(scoreId, instrument, variant)
    if (isError(result)) setError(result.error)
  }

  function chooseTarget(instrument: string, variant?: string) {
    const versions = variantsOf(instrument)
    setTarget({ instrument, variant: variant ?? versions[0]?.id ?? '' })
    setOctave(0)
  }

  async function create() {
    if (!request) return
    const version = target ? variantsOf(target.instrument).find((v) => v.id === target.variant) : null
    const name =
      mode === 'instrument' && target && version
        ? `${label(target.instrument)} ${variantLabel(version, t)}`
        : t('transpose.intervalName', {
            instrument: source ? label(source.instrument) : t('scores.untitled'),
            interval: t(`transpose.intervals.${interval}`),
            direction: t(`transpose.${direction}`),
          })
    setBusy(true)
    try {
      const result = await api.transpose_score(scoreId, { ...request, name })
      if (isError(result)) setError(result.error)
      else onCreated(result.score)
    } catch {
      setError('unexpected')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation" onClick={onClose}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="transpose-title"
        onClick={(e) => e.stopPropagation()}>
        <h2 id="transpose-title">{t('transpose.title')}</h2>

        <fieldset>
          <legend>{t('transpose.source')}</legend>
          <label>
            {t('transpose.instrument')}
            <select value={source?.instrument ?? ''} disabled={busy}
              onChange={(e) => chooseSource(e.target.value, variantsOf(e.target.value)[0]?.id ?? '')}>
              <option value="">{t('transpose.choose')}</option>
              {table.map((i) => (
                <option key={i.id} value={i.id}>{label(i.id)}</option>
              ))}
            </select>
          </label>
          {source && (
            <label>
              {t('transpose.versionLabel')}
              <select value={source.variant} disabled={busy}
                onChange={(e) => chooseSource(source.instrument, e.target.value)}>
                {variantsOf(source.instrument).map((v) => (
                  <option key={v.id} value={v.id}>{variantLabel(v, t)}</option>
                ))}
              </select>
            </label>
          )}
          {source && detected && <p className="question-note">{t('transpose.detected')}</p>}
        </fieldset>

        <fieldset>
          <legend>{t('transpose.how')}</legend>
          <label className="radio">
            <input type="radio" checked={mode === 'instrument'} onChange={() => setMode('instrument')} />
            {t('transpose.forInstrument')}
          </label>
          <label className="radio">
            <input type="radio" checked={mode === 'interval'} onChange={() => setMode('interval')} />
            {t('transpose.byInterval')}
          </label>
          {mode === 'instrument' ? (
            <div className="editor-row">
              <label>
                {t('transpose.target')}
                <select value={target?.instrument ?? ''} disabled={busy}
                  onChange={(e) => chooseTarget(e.target.value)}>
                  <option value="">{t('transpose.choose')}</option>
                  {table.filter((i) => variantsOf(i.id).length > 0).map((i) => (
                    <option key={i.id} value={i.id}>{label(i.id)}</option>
                  ))}
                </select>
              </label>
              {target && (
                <label>
                  {t('transpose.versionLabel')}
                  <select value={target.variant} disabled={busy}
                    onChange={(e) => chooseTarget(target.instrument, e.target.value)}>
                    {variantsOf(target.instrument).map((v) => (
                      <option key={v.id} value={v.id}>{variantLabel(v, t)}</option>
                    ))}
                  </select>
                </label>
              )}
              {!source && <p className="error">{t('transpose.needSource')}</p>}
            </div>
          ) : (
            <div className="editor-row">
              <label>
                {t('transpose.interval')}
                <select value={interval} onChange={(e) => setIntervalName(e.target.value)}>
                  {INTERVALS.map((i) => (
                    <option key={i} value={i}>{t(`transpose.intervals.${i}`)}</option>
                  ))}
                </select>
              </label>
              <label>
                {t('transpose.direction')}
                <select value={direction} onChange={(e) => setDirection(e.target.value as 'up' | 'down')}>
                  <option value="up">{t('transpose.up')}</option>
                  <option value="down">{t('transpose.down')}</option>
                </select>
              </label>
            </div>
          )}
          <label>
            {t('transpose.octave')}
            <select value={octave} onChange={(e) => setOctave(Number(e.target.value))}>
              {OCTAVES.map((k) => (
                <option key={k} value={k}>
                  {t(`transpose.octaves.${k < 0 ? 'down' : k > 0 ? 'up' : 'none'}`, { count: Math.abs(k) })}
                  {report && report.suggested_octave === k && k !== octave ? ` ${t('transpose.advised')}` : ''}
                </option>
              ))}
            </select>
          </label>
        </fieldset>

        {report && (
          <div className="transpose-preview" role="status">
            <p>{t('transpose.keyResult', { key: report.keys.map((k) => keyText(k, t)).join(', ') })}</p>
            {report.out_of_range > 0 ? (
              <p className="error">
                {t('transpose.outOfRange', { count: report.out_of_range, total: report.notes })}
                {report.suggested_octave !== octave &&
                  ` ${t('transpose.tryOctave', {
                    octave: t(`transpose.octaves.${report.suggested_octave < 0 ? 'down' : 'up'}`, {
                      count: Math.abs(report.suggested_octave),
                    }),
                  })}`}
              </p>
            ) : (
              mode === 'instrument' && <p>{t('transpose.inRange')}</p>
            )}
          </div>
        )}
        {error && <p className="error">{t(`errors.${error}`, { defaultValue: t('errors.unexpected') })}</p>}

        <div className="dialog-actions">
          <button type="button" onClick={onClose}>{t('transpose.cancel')}</button>
          <button type="button" className="primary" disabled={busy || !request || !report} onClick={create}>
            {t('transpose.create')}
          </button>
        </div>
      </div>
    </div>
  )
}
