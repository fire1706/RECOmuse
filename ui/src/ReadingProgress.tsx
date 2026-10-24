/**
 * Barre de progression de la lecture d'une partition.
 *
 * Montre l'étape en cours (et la page : « page 3 sur 12 »), la part du travail faite,
 * le temps restant estimé, et un bouton « Annuler ». Les données viennent du moteur
 * (Api.get_progress), relues régulièrement par App.
 */
import { useTranslation } from 'react-i18next'

import type { ReadingState } from './bridge'

interface Props {
  state: ReadingState
  onCancel: () => void
}

// Avant ce seuil, le temps restant serait trop incertain : on ne l'affiche pas encore.
const ETA_MIN_FRACTION = 0.03
const ETA_MIN_ELAPSED_S = 8

/**
 * Temps restant estimé en secondes : le temps déjà passé, au même rythme, pour la part
 * qui reste. null tant que l'estimation n'a pas de sens.
 */
export function remainingSeconds(fraction: number, elapsed: number): number | null {
  if (fraction < ETA_MIN_FRACTION || elapsed < ETA_MIN_ELAPSED_S || fraction >= 1) return null
  return (elapsed * (1 - fraction)) / fraction
}

export default function ReadingProgress({ state, onCancel }: Props) {
  const { t } = useTranslation()
  const percent = Math.round(state.fraction * 100)
  const remaining = remainingSeconds(state.fraction, state.elapsed)
  const stage = t(`open.stage.${state.stage}`, { defaultValue: t('open.stage.import') })
  const page =
    state.page !== null && state.pages !== null && state.pages > 1
      ? t('open.page', { page: state.page, pages: state.pages })
      : null

  let eta: string
  if (state.cancelling) eta = t('open.cancelling')
  else if (remaining === null) eta = t('open.etaUnknown')
  else if (remaining < 60) eta = t('open.etaSoon')
  else eta = t('open.eta', { count: Math.round(remaining / 60) })

  return (
    <div className="reading">
      <p className="reading-stage">
        {stage}
        {page && <span className="reading-page"> — {page}</span>}
      </p>
      <div
        className="reading-bar"
        role="progressbar"
        aria-label={t('open.progress')}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <div className="reading-bar-fill" style={{ width: `${percent}%` }} />
      </div>
      <div className="reading-footer">
        <span>
          {percent} % · {eta}
        </span>
        <button type="button" onClick={onCancel} disabled={state.cancelling}>
          {t('open.cancel')}
        </button>
      </div>
    </div>
  )
}
