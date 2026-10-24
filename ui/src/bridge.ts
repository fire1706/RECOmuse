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
  /** Mesure concernée (montrée dans la vue côte à côte). */
  measure_id: string | null
  params: Record<string, unknown>
  choices: Choice[]
  confidence: number
  /** Nombre de doutes qu'une seule réponse règle. */
  issue_count: number
  /** Extrait de la page (data URL PNG), ou null. */
  image: string | null
}

/** Un passage à vérifier à l'œil (doute sans question). */
export interface Check {
  /** Type de doute : checks.<code>. */
  code: string
  measure_numbers: number[]
  measure_id: string | null
  page: number | null
  details: Record<string, string | number>
}

/** Une mesure dessinée sur une page (boîte en pixels de l'image à 300 dpi). */
export interface PageMeasure {
  id: string
  number: number
  length: number
  part_id: string
  bbox: [number, number, number, number]
}

/** Une page de la partition d'origine, pour la vue côte à côte. */
export interface PageView {
  score_id: number
  page: number
  /** Image de la page (data URL JPEG), ou null si elle manque. */
  image: string | null
  width: number
  height: number
  measures: PageMeasure[]
  /** Pages de musique de la partition. */
  pages: number[]
}

/** La partition reconnue, en MEI pour Verovio. */
export interface Rendering {
  score_id: number
  mei: string
  /** Identifiant MEI → identifiant du symbole du modèle. */
  symbols: Record<string, string>
  /** Identifiant MEI → identifiant de la mesure du modèle. */
  measures: Record<string, string>
  /** Identifiant de mesure → page de la partition d'origine. */
  measure_pages: Record<string, number | null>
}

/** Questions encore à poser pour une partition. */
export interface QuestionsState {
  score_id: number
  questions: Question[]
  /** Points sans question (à revoir dans la vue côte à côte). */
  unasked: number
  checks: Check[]
  /** Nombre d'autres parties du morceau auxquelles la partition a été comparée. */
  compared_parts: number
  answered: number
  can_undo: boolean
}

/** Un symbole d'une mesure (note, silence, clé, armure, chiffrage, pause multiple). */
export interface MeasureSymbol {
  id: string
  kind: 'note' | 'rest' | 'clef' | 'key' | 'time' | 'multirest'
  /** Valeur du modèle ; « written » : durée écrite en noires (« 1/2 » = croche). */
  value: Record<string, unknown>
  confidence: number
  source: string
}

/** Contenu d'une mesure pour l'éditeur (voir src/recomuse/editing.py). */
export interface MeasureDetails {
  id: string
  number: number
  page: number | null
  length: number
  part_id: string
  /** Durée lue et attendue, en noires (« 7/2 »), ou null. */
  duration: string | null
  expected: string | null
  attributes: MeasureSymbol[]
  events: MeasureSymbol[]
  /** Clé, armure (dièses + / bémols -) et chiffrage en vigueur. */
  state: { clef: { sign: string; line: number | null; octave_change?: number }; fifths: number; time: string | null }
  previous: string | null
  next: string | null
  can_undo: boolean
}

/** Un geste d'édition (op : pitch, octave, alter, duration, tie, remove, add_note,
 * add_rest, time, key, clef, multirest, set), avec ses paramètres. */
export type Edit = { op: string } & Record<string, unknown>

/** Résultat d'un geste : la mesure concernée et le symbole à garder choisi. */
export interface EditResult {
  measure_id: string | null
  symbol_id: string | null
  corrections: number[]
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
  get_page(scoreId: number, page: number): Promise<PageView | EngineError>
  get_rendering(scoreId: number): Promise<Rendering | EngineError>
  get_measure(scoreId: number, measureId: string): Promise<MeasureDetails | EngineError>
  edit_score(scoreId: number, edit: Edit): Promise<EditResult | EngineError>
  undo_edit(scoreId: number): Promise<{ measure_id: string } | EngineError>
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
