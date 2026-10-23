// Pont vers le moteur Python.
//
// Dans la fenêtre pywebview, les méthodes de la classe Python `Api` (src/recomuse/api.py)
// sont disponibles sous `window.pywebview.api`, mais seulement après l'événement
// « pywebviewready ». Ce fichier cache ces détails au reste de l'interface.

/** Informations renvoyées par Api.get_app_info() côté Python. */
export interface AppInfo {
  version: string
  python_version: string
  platform: string
  database_path: string
  correction_count: number
}

/** Méthodes Python accessibles depuis l'interface (à compléter au fil des tâches). */
export interface PythonApi {
  ping(): Promise<string>
  get_app_info(): Promise<AppInfo>
}

declare global {
  interface Window {
    pywebview?: { api: PythonApi }
  }
}

/** Délai d'attente par défaut du pont, en millisecondes. */
const DEFAULT_TIMEOUT_MS = 5000

/**
 * Attend que le pont Python soit prêt et le renvoie.
 *
 * Renvoie `null` si le pont n'apparaît pas à temps : c'est le cas quand l'interface
 * est ouverte dans un simple navigateur (npm run dev) au lieu de la fenêtre RECOmuse.
 */
export function waitForBridge(timeoutMs = DEFAULT_TIMEOUT_MS): Promise<PythonApi | null> {
  if (window.pywebview?.api) {
    return Promise.resolve(window.pywebview.api)
  }

  return new Promise((resolve) => {
    const onReady = () => {
      window.clearTimeout(timer)
      resolve(window.pywebview?.api ?? null)
    }
    const timer = window.setTimeout(() => {
      window.removeEventListener('pywebviewready', onReady)
      resolve(null)
    }, timeoutMs)
    window.addEventListener('pywebviewready', onReady, { once: true })
  })
}
