// Vue de droite : la partition telle que le logiciel l'a comprise, dessinée par Verovio.
// Cliquer une mesure la choisit (sa page d'origine s'affiche alors à gauche) ; la mesure
// choisie ailleurs (scan, question) est surlignée ici.

import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { isError, type PythonApi, type Rendering } from './bridge'
import { renderMei } from './verovio'

interface ScoreViewProps {
  api: PythonApi
  scoreId: number
  /** Change à chaque correction : le rendu est refait. */
  version: number
  selectedMeasure: string | null
  /** Symbole choisi (note, silence...) : dessiné en bleu. */
  selectedSymbol?: string | null
  /** Mesure cliquée, sa page d'origine, et le symbole cliqué (ou null). */
  onSelect: (measureId: string, page: number | null, symbolId: string | null) => void
  /** Permet aux tests de remplacer Verovio. */
  render?: (mei: string) => Promise<string[]>
}

/** Mesure dessinée dont le rectangle contient le point (x, y) de l'écran. */
export function measureAt(root: Element | null, x: number, y: number): Element | null {
  for (const measure of root?.querySelectorAll('g.measure') ?? []) {
    const box = measure.getBoundingClientRect()
    if (x >= box.left && x <= box.right && y >= box.top && y <= box.bottom) return measure
  }
  return null
}

export default function ScoreView({
  api, scoreId, version, selectedMeasure, selectedSymbol = null, onSelect, render = renderMei,
}: ScoreViewProps) {
  const { t } = useTranslation()
  const [rendering, setRendering] = useState<Rendering | null>(null)
  const [pages, setPages] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const container = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    setError(null)
    api
      .get_rendering(scoreId)
      .then(async (result) => {
        if (cancelled) return
        if (isError(result)) {
          setError(result.error)
          return
        }
        const svgs = await render(result.mei)
        if (cancelled) return
        setRendering(result)
        setPages(svgs)
      })
      .catch(() => !cancelled && setError('rendering_failed'))
    return () => {
      cancelled = true
    }
  }, [api, scoreId, version, render])

  // Identifiant du modèle (mesure ou symbole) → identifiant MEI (celui du dessin).
  const meiIds = useMemo(() => {
    const table: Record<string, string> = {}
    for (const [meiId, measureId] of Object.entries(rendering?.measures ?? {})) table[measureId] = meiId
    for (const [meiId, symbolId] of Object.entries(rendering?.symbols ?? {})) table[symbolId] = meiId
    return table
  }, [rendering])

  // Dessine en bleu le symbole choisi.
  useEffect(() => {
    const root = container.current
    if (!root) return
    root.querySelectorAll('.selected-symbol').forEach((el) => el.classList.remove('selected-symbol'))
    const meiId = selectedSymbol ? meiIds[selectedSymbol] : undefined
    if (meiId) root.querySelector(`#${CSS.escape(meiId)}`)?.classList.add('selected-symbol')
  }, [selectedSymbol, meiIds, pages])

  // Surligne la mesure choisie et l'amène à l'écran.
  useEffect(() => {
    const root = container.current
    if (!root) return
    root.querySelectorAll('.measure.selected').forEach((el) => el.classList.remove('selected'))
    const meiId = selectedMeasure ? meiIds[selectedMeasure] : undefined
    if (!meiId) return
    const element = root.querySelector(`#${CSS.escape(meiId)}`)
    element?.classList.add('selected')
    element?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
  }, [selectedMeasure, meiIds, pages])

  function onClick(event: React.MouseEvent<HTMLDivElement>) {
    // Un clic entre les traits du dessin ne touche aucun élément de la mesure : on prend
    // alors la mesure dont le rectangle contient le point cliqué.
    const measure =
      (event.target as Element).closest('g.measure') ??
      measureAt(container.current, event.clientX, event.clientY)
    const measureId = measure && rendering?.measures[measure.id]
    if (measureId) onSelect(measureId, rendering?.measure_pages[measureId] ?? null, symbolAt(event.target as Element))
  }

  /** Symbole du modèle dessiné à cet endroit (la note, le silence...), ou null. */
  function symbolAt(target: Element): string | null {
    for (let el: Element | null = target; el && el !== container.current; el = el.parentElement) {
      const symbolId = el.id ? rendering?.symbols[el.id] : undefined
      if (symbolId) return symbolId
    }
    return null
  }

  if (error) return <p className="error">{t(`errors.${error}`, { defaultValue: t('errors.unexpected') })}</p>
  if (!pages) return <p className="empty">{t('score.loading')}</p>

  return (
    // Le dessin est produit par Verovio à partir du modèle (aucun texte venu de l'extérieur).
    <div className="score-view" ref={container} onClick={onClick} role="presentation">
      {pages.map((svg, k) => (
        <div key={k} className="score-page" dangerouslySetInnerHTML={{ __html: svg }} />
      ))}
    </div>
  )
}
