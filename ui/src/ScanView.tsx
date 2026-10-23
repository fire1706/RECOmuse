// Vue de gauche : une page de la partition d'origine, chaque mesure lue encadrée.
// Cliquer une mesure la choisit (elle est alors montrée aussi dans le rendu, à droite).

import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { isError, type PageView, type PythonApi } from './bridge'

interface ScanViewProps {
  api: PythonApi
  scoreId: number
  page: number
  /** Change à chaque correction : la page est relue (les mesures ont pu changer). */
  version: number
  selectedMeasure: string | null
  onPage: (page: number) => void
  onSelect: (measureId: string, page: number) => void
}

/** Position d'une boîte (pixels de l'image d'origine) en pourcentages de la page. */
export function boxStyle(bbox: [number, number, number, number], width: number, height: number) {
  const [x, y, w, h] = bbox
  return {
    left: `${(100 * x) / width}%`,
    top: `${(100 * y) / height}%`,
    width: `${(100 * w) / width}%`,
    height: `${(100 * h) / height}%`,
  }
}

export default function ScanView({ api, scoreId, page, version, selectedMeasure, onPage, onSelect }: ScanViewProps) {
  const { t } = useTranslation()
  const [view, setView] = useState<PageView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const container = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    setError(null)
    api
      .get_page(scoreId, page)
      .then((result) => {
        if (cancelled) return
        if (isError(result)) setError(result.error)
        else setView(result)
      })
      .catch(() => !cancelled && setError('unexpected'))
    return () => {
      cancelled = true
    }
  }, [api, scoreId, page, version])

  // La mesure choisie est amenée à l'écran.
  useEffect(() => {
    if (!selectedMeasure) return
    const box = container.current?.querySelector(`[data-measure="${CSS.escape(selectedMeasure)}"]`)
    box?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
  }, [selectedMeasure, view])

  if (error) return <p className="error">{t(`errors.${error}`, { defaultValue: t('errors.unexpected') })}</p>
  if (!view || view.page !== page) return <p className="empty">{t('scan.loading')}</p>

  const index = view.pages.indexOf(page)
  return (
    <div className="scan-view">
      <div className="page-nav">
        <button type="button" disabled={index <= 0} onClick={() => onPage(view.pages[index - 1])}>
          {t('scan.previous')}
        </button>
        <span>{t('scan.page', { page, count: view.pages.length })}</span>
        <button type="button" disabled={index < 0 || index >= view.pages.length - 1}
          onClick={() => onPage(view.pages[index + 1])}>
          {t('scan.next')}
        </button>
      </div>
      {view.image ? (
        <div className="scan-page" ref={container}>
          <img src={view.image} alt={t('scan.imageAlt', { page })} />
          {view.measures.map((measure) => (
            <button
              key={measure.id}
              type="button"
              data-measure={measure.id}
              className={`measure-box${measure.id === selectedMeasure ? ' selected' : ''}`}
              style={boxStyle(measure.bbox, view.width, view.height)}
              title={t('scan.measure', { number: measure.number })}
              aria-label={t('scan.measure', { number: measure.number })}
              aria-pressed={measure.id === selectedMeasure}
              onClick={() => onSelect(measure.id, page)}
            />
          ))}
        </div>
      ) : (
        <p className="empty">{t('scan.noImage')}</p>
      )}
    </div>
  )
}
