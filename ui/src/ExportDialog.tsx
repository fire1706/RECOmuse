// Fenêtre « Exporter » : enregistrer la partition pour MuseScore (.mscz), en MusicXML ou
// en MIDI (joué à la hauteur réelle). Prévient s'il reste des doutes non réglés : le
// fichier contiendra alors les erreurs encore présentes.

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { type ExportFormat, type ExportOptions, type ExportResult, isError, type PythonApi } from './bridge'

interface ExportDialogProps {
  api: PythonApi
  scoreId: number
  onClose: () => void
}

const FORMATS: ExportFormat[] = ['musescore', 'musicxml', 'midi']

export default function ExportDialog({ api, scoreId, onClose }: ExportDialogProps) {
  const { t } = useTranslation()
  const [options, setOptions] = useState<ExportOptions | null>(null)
  const [format, setFormat] = useState<ExportFormat>('musescore')
  const [result, setResult] = useState<ExportResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    api
      .get_export_options(scoreId)
      .then((value) => {
        if (cancelled) return
        if (isError(value)) setError(value.error)
        else setOptions(value)
      })
      .catch(() => !cancelled && setError('unexpected'))
    return () => {
      cancelled = true
    }
  }, [api, scoreId])

  async function save() {
    if (!options) return
    setError(null)
    setResult(null)
    const path = await api.choose_save_path(t(`export.filters.${format}`), options.default_name, format)
    if (!path) return
    setBusy(true)
    try {
      const written = await api.export_score(scoreId, format, path)
      if (isError(written)) setError(written.error)
      else setResult(written)
    } catch {
      setError('unexpected')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation" onClick={onClose}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="export-title"
        onClick={(e) => e.stopPropagation()}>
        <h2 id="export-title">{t('export.title')}</h2>
        {!options && !error && <p className="empty">{t('export.loading')}</p>}
        {options && (
          <>
            <fieldset>
              <legend>{t('export.format')}</legend>
              {FORMATS.map((value) => (
                <label key={value} className="radio">
                  <input type="radio" name="format" checked={format === value} disabled={busy}
                    onChange={() => setFormat(value)} />
                  <span>
                    <strong>{t(`export.formats.${value}`)}</strong> — {t(`export.descriptions.${value}`)}
                  </span>
                </label>
              ))}
              {format === 'musescore' && !options.musescore && (
                <p className="question-note">{t('export.noMusescore')}</p>
              )}
            </fieldset>
            {(options.questions > 0 || options.checks > 0) && (
              <p className="error">
                {t('export.pending', {
                  questions: t('export.questions', { count: options.questions }),
                  checks: t('export.checks', { count: options.checks }),
                })}
              </p>
            )}
          </>
        )}
        {busy && <p className="reading">{t(`export.writing.${format}`)}</p>}
        {result && (
          <div className="transpose-preview" role="status">
            <p>{t('export.saved', { path: result.path })}</p>
            {result.fallback && (
              <p className="question-note">{t(`export.fallback.${result.fallback}`, { defaultValue: t('export.fallback.musescore_failed') })}</p>
            )}
          </div>
        )}
        {error && <p className="error">{t(`errors.${error}`, { defaultValue: t('errors.unexpected') })}</p>}
        <div className="dialog-actions">
          <button type="button" onClick={onClose}>{t('export.close')}</button>
          <button type="button" className="primary" disabled={busy || !options} onClick={save}>
            {t('export.save')}
          </button>
        </div>
      </div>
    </div>
  )
}
