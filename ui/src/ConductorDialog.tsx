// Fenêtre « Conducteur » :
// - pour un conducteur (tous les instruments sur chaque système) : en extraire les parties,
//   une partition par instrument ;
// - pour une partie : assembler un conducteur avec les autres parties du même morceau.

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { isError, type PythonApi, type ScoreSummary } from './bridge'

interface ConductorDialogProps {
  api: PythonApi
  score: ScoreSummary
  /** Nouvelles partitions créées (parties extraites, ou conducteur assemblé). */
  onCreated: (scores: ScoreSummary[]) => void
  onClose: () => void
}

export default function ConductorDialog({ api, score, onCreated, onClose }: ConductorDialogProps) {
  const { t } = useTranslation()
  const conductor = score.instruments.length > 1
  const [piece, setPiece] = useState<ScoreSummary[] | null>(null)
  const [chosen, setChosen] = useState<number[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Parties du même morceau, cochées d'office (sauf copies et conducteurs).
  useEffect(() => {
    if (conductor) return
    let cancelled = false
    api
      .get_piece_scores(score.score_id)
      .then((scores) => {
        if (cancelled) return
        setPiece(scores)
        setChosen(scores.filter((s) => !s.derived && s.instruments.length === 0).map((s) => s.score_id))
      })
      .catch(() => !cancelled && setError('unexpected'))
    return () => {
      cancelled = true
    }
  }, [api, score.score_id, conductor])

  async function run(request: () => Promise<ScoreSummary[] | { error: string }>) {
    setBusy(true)
    setError(null)
    try {
      const result = await request()
      if (isError(result)) setError(result.error)
      else onCreated(result)
    } catch {
      setError('unexpected')
    } finally {
      setBusy(false)
    }
  }

  const extract = () =>
    run(async () => {
      const result = await api.extract_parts(score.score_id)
      return isError(result) ? result : result.scores
    })

  const assemble = () =>
    run(async () => {
      const result = await api.assemble_conductor(chosen)
      return isError(result) ? result : [result.score]
    })

  const toggle = (id: number) =>
    setChosen(chosen.includes(id) ? chosen.filter((k) => k !== id) : [...chosen, id])

  return (
    <div className="dialog-backdrop" role="presentation" onClick={onClose}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="conductor-title"
        onClick={(e) => e.stopPropagation()}>
        <h2 id="conductor-title">{t('conductor.title')}</h2>
        {conductor ? (
          <>
            <p>{t('conductor.isConductor', { count: score.instruments.length })}</p>
            <ul className="rules">
              {score.instruments.map((name, k) => (
                <li key={k}>{name ?? t('conductor.unnamed', { number: k + 1 })}</li>
              ))}
            </ul>
            <p className="question-note">{t('conductor.extractHelp')}</p>
          </>
        ) : (
          <>
            <p className="question-note">{t('conductor.assembleHelp')}</p>
            {piece !== null && piece.length < 2 && <p className="empty">{t('conductor.alone')}</p>}
            {piece !== null && piece.length >= 2 && (
              <ul className="rules">
                {piece.map((s) => (
                  <li key={s.score_id}>
                    <label>
                      <input type="checkbox" checked={chosen.includes(s.score_id)} disabled={busy}
                        onChange={() => toggle(s.score_id)} />
                      <span>
                        {s.instrument ?? s.source_name ?? t('scores.untitled')}
                        {s.derived && ` (${t(`conductor.derived.${s.derived}`)})`}
                        {s.instruments.length > 1 && ` (${t('conductor.aConductor')})`}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
        {error && <p className="error">{t(`errors.${error}`, { defaultValue: t('errors.unexpected') })}</p>}
        <div className="dialog-actions">
          <button type="button" onClick={onClose}>{t('conductor.cancel')}</button>
          {conductor ? (
            <button type="button" className="primary" disabled={busy} onClick={extract}>
              {t('conductor.extract', { count: score.instruments.length })}
            </button>
          ) : (
            <button type="button" className="primary" disabled={busy || chosen.length < 2} onClick={assemble}>
              {t('conductor.assemble', { count: chosen.length })}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
