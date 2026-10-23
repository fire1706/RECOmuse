// Chargement de Verovio (dessin des partitions), à la première utilisation seulement :
// la bibliothèque pèse plusieurs mégaoctets, inutile de la charger avant d'en avoir besoin.

/** Ce que l'interface utilise de la boîte à outils Verovio. */
export interface VerovioToolkitLike {
  setOptions(options: Record<string, unknown>): void
  loadData(data: string): boolean
  getPageCount(): number
  renderToSVG(page: number): string
  getPageWithElement(id: string): number
}

/** Réglages du dessin : largeur de page en unités Verovio, taille, coupure des lignes. */
export const VEROVIO_OPTIONS = {
  pageWidth: 2100,
  scale: 40,
  adjustPageHeight: true,
  breaks: 'auto',
  svgViewBox: true,
  header: 'none',
  footer: 'none',
}

let toolkit: Promise<VerovioToolkitLike> | null = null

/** Renvoie la boîte à outils Verovio (chargée une seule fois). */
export function loadVerovio(): Promise<VerovioToolkitLike> {
  toolkit ??= (async () => {
    const [{ default: createVerovioModule }, { VerovioToolkit }] = await Promise.all([
      import('verovio/wasm'),
      import('verovio/esm'),
    ])
    const tk = new VerovioToolkit(await createVerovioModule())
    tk.setOptions(VEROVIO_OPTIONS)
    return tk
  })()
  return toolkit
}

/** Dessine un texte MEI : une image SVG par page. */
export async function renderMei(mei: string): Promise<string[]> {
  const tk = await loadVerovio()
  if (!tk.loadData(mei)) throw new Error('Verovio : MEI illisible')
  const pages: string[] = []
  for (let page = 1; page <= tk.getPageCount(); page++) pages.push(tk.renderToSVG(page))
  return pages
}
