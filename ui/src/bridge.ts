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

/** Une partition lue (une partie d'un fichier). */
export interface ScoreSummary {
  score_id: number
  title: string | null
  instrument: string | null
  source_name: string | null
  pages: number[]
  measure_count: number
}

/** Une réponse possible à une question. */
export interface Choice {
  id: string
  /** Étiquette traduite : questions.choices.<label>. */
  label: string
  params: Record<string, unknown>
  /** « count » : l'utilisateur tape un nombre de mesures. */
  input: string | null
}

/** Une question posée au musicien (voir src/recomuse/questions/questions.py). */
export interface Question {
  key: string
  /** Type de doute : questions.text.<code>. */
  code: string
  part_id: string
  measure_numbers: number[]
  page: number | null
  params: Record<string, unknown>
  choices: Choice[]
  confidence: number
  /** Nombre de doutes qu'une seule réponse règle. */
  issue_count: number
  /** Extrait de la page (data URL PNG), ou null. */
  image: string | null
}

/** Questions encore à poser pour une partition. */
export interface QuestionsState {
  score_id: number
  questions: Question[]
  /** Points sans question (à revoir dans la vue côte à côte). */
  unasked: number
  answered: number
  can_undo: boolean
}

/** Erreur renvoyée par le moteur : un code traduit par errors.<code>. */
export interface EngineError {
  error: string
}

export type OpenResult = { scores: ScoreSummary[] } | EngineError

/** Méthodes Python accessibles depuis l'interface. */
export interface PythonApi {
  ping(): Promise<string>
  get_app_info(): Promise<AppInfo>
  choose_file(filterLabel: string): Promise<string | null>
  open_file(path: string): Promise<OpenResult>
  get_progress(): Promise<{ stage: string | null }>
  list_scores(): Promise<ScoreSummary[]>
  get_questions(scoreId: number): Promise<QuestionsState | EngineError>
  answer_question(
    scoreId: number,
    key: string,
    choiceId: string,
    value: number | null,
  ): Promise<QuestionsState | EngineError>
  undo_answer(scoreId: number): Promise<QuestionsState | EngineError>
}

/** Vrai si la réponse du moteur est une erreur. */
export function isError(value: unknown): value is EngineError {
  return typeof value === 'object' && value !== null && 'error' in value
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
