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
/** Ce que la lecture a remarqué (image trop petite, page non lue...), par type. */
export interface ReadingWarning {
  code: 'low_resolution' | 'audiveris_skipped' | 'large_skew'
  pages: number[]
  /** Basse résolution : la plus basse résolution d'origine, en dpi. */
  dpi?: number
}

export interface ScoreSummary {
  score_id: number
  title: string | null
  instrument: string | null
  source_name: string | null
  pages: number[]
  measure_count: number
  /** Conducteur : le nom de chacun de ses instruments (vide pour une partie). */
  instruments: (string | null)[]
  /** Partition tirée d'autres : partie extraite d'un conducteur, conducteur assemblé. */
  derived: 'extracted' | 'assembled' | null
  /** Avertissements de lecture (absents des partitions enregistrées avant). */
  warnings?: ReadingWarning[]
  /** Partie déjà lue et corrigée : corrections et réponses reprises (à l'ouverture). */
  memory?: {
    from?: number
    applied: number
    skipped: number
    answers: number
    read_at: string
    /** Corrections venues d'un pack d'apprentissage (d'un autre membre). */
    from_pack?: number
    author?: string | null
  }
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
  /** Réponses données par les règles apprises, et reprises d'une lecture précédente. */
  answered_by_rules: number
  answered_by_memory: number
  can_undo: boolean
}

/** Un symbole d'une mesure (note, silence, clé, armure, chiffrage, pause multiple). */
export interface MeasureSymbol {
  id: string
  kind: 'note' | 'rest' | 'clef' | 'key' | 'time' | 'tempo' | 'multirest'
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

/** Un instrument de la table (src/recomuse/instruments/instruments.json). */
export interface InstrumentInfo {
  id: string
  /** Nom affiché, par langue. */
  label: Record<string, string>
  variants: { id: string; key: string | null; clef: string; transposable: boolean }[]
}

/** Instrument et version d'une partition (detected : reconnus d'après le nom). */
export interface ScoreInstrument {
  instrument_id: string | null
  variant_id: string | null
  detected: boolean
}

/** Une transposition demandée (voir src/recomuse/instruments/parts.py). */
export type TranspositionRequest =
  | { mode: 'instrument'; target: { instrument: string; variant: string }; octave: number; name?: string }
  | { mode: 'interval'; interval: string; direction: 'up' | 'down'; octave: number; name?: string }

/** Ce que donne une transposition : armures, notes hors de l'étendue, octave conseillée. */
export interface TranspositionReport {
  interval: { steps: number; semitones: number }
  keys: number[]
  notes: number
  out_of_range: number
  suggested_octave: number
}

/** Formats d'export proposés. */
export type ExportFormat = 'musescore' | 'musicxml' | 'midi'

/** Avant d'exporter : nom proposé, MuseScore présent, doutes encore ouverts. */
export interface ExportOptions {
  default_name: string
  musescore: boolean
  questions: number
  checks: number
}

/** Fichier écrit ; fallback : raison d'un MusicXML écrit à la place du MuseScore. */
export interface ExportResult {
  path: string
  format: ExportFormat
  fallback: string | null
}

/** Une règle apprise (voir src/recomuse/learning/rules.py). */
export interface Rule {
  key: string
  /** Type de doute (code) et ce qui le caractérise. */
  signature: { code: string } & Record<string, unknown>
  choice_id: string
  choice_label: string | null
  evidence: number
  agreeing: number
  enabled: boolean
  /** Réponses venues de packs d'apprentissage. */
  from_packs: number
}

/** Un pack d'apprentissage importé (voir src/recomuse/learning/packs.py). */
export interface PackInfo {
  id: number
  author: string | null
  created_at: string
  imported_at: string
  answers: number
  scores: number
}

/** Erreur renvoyée par le moteur : un code traduit par errors.<code>. */
export interface EngineError {
  error: string
}

export type OpenResult = { scores: ScoreSummary[] } | EngineError

/** Où en est la lecture d'un fichier (barre de progression). */
export interface ReadingState {
  stage: string // import, vector, texts, audiveris, model, done
  page: number | null // page en cours dans l'étape (à partir de 1)
  pages: number | null
  fraction: number // part du travail faite, de 0 à 1
  elapsed: number // secondes depuis le début
  cancelling: boolean // « Annuler » demandé, arrêt en cours
}

/** Méthodes Python accessibles depuis l'interface. */
export interface PythonApi {
  ping(): Promise<string>
  get_app_info(): Promise<AppInfo>
  choose_file(filterLabel: string): Promise<string | null>
  open_file(path: string): Promise<OpenResult>
  get_progress(): Promise<ReadingState | { stage: null }>
  cancel_reading(): Promise<{ cancelling: boolean }>
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
  get_instruments(): Promise<InstrumentInfo[]>
  get_score_instrument(scoreId: number): Promise<ScoreInstrument | EngineError>
  set_score_instrument(scoreId: number, instrumentId: string, variantId: string): Promise<ScoreInstrument | EngineError>
  check_transposition(scoreId: number, request: TranspositionRequest): Promise<TranspositionReport | EngineError>
  transpose_score(
    scoreId: number,
    request: TranspositionRequest,
  ): Promise<{ score: ScoreSummary; report: TranspositionReport } | EngineError>
  get_export_options(scoreId: number): Promise<ExportOptions | EngineError>
  choose_save_path(filterLabel: string, defaultName: string, format: ExportFormat): Promise<string | null>
  export_score(scoreId: number, format: ExportFormat, path: string): Promise<ExportResult | EngineError>
  extract_parts(scoreId: number): Promise<{ scores: ScoreSummary[] } | EngineError>
  get_piece_scores(scoreId: number): Promise<ScoreSummary[]>
  assemble_conductor(scoreIds: number[]): Promise<{ score: ScoreSummary } | EngineError>
  get_rules(): Promise<Rule[]>
  set_rule_enabled(key: string, enabled: boolean): Promise<{ rules: Rule[] } | EngineError>
  choose_pack_file(save: boolean, filterLabel: string, defaultName: string): Promise<string | null>
  export_pack(
    path: string,
    author: string,
    includeScores: boolean,
  ): Promise<{ path: string; answers: number; scores: number } | EngineError>
  import_pack(path: string): Promise<PackInfo | EngineError>
  list_packs(): Promise<PackInfo[]>
  remove_pack(packId: number): Promise<{ packs: PackInfo[] } | EngineError>
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
