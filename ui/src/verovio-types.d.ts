// Types du paquet « verovio », qui n'en fournit pas (seulement ce que l'interface utilise).

declare module 'verovio/wasm' {
  const createVerovioModule: () => Promise<unknown>
  export default createVerovioModule
}

declare module 'verovio/esm' {
  export class VerovioToolkit {
    constructor(module: unknown)
    setOptions(options: Record<string, unknown>): void
    loadData(data: string): boolean
    getPageCount(): number
    renderToSVG(page: number): string
    getPageWithElement(id: string): number
  }
}
