// Faux moteur Python pour les tests de l'interface (aucune fenêtre pywebview).

import type { AppInfo, PythonApi, Question, QuestionsState } from './bridge'

export const fakeInfo: AppInfo = {
  version: '0.1.0',
  python_version: '3.12.10',
  platform: 'win32',
  database_path: 'C:/fictif/recomuse.sqlite3',
  correction_count: 3,
}

/** Question « pause multiple manquée » : 8 mesures, autre nombre, une seule mesure. */
export const restQuestion: Question = {
  key: 'multirest:P1:m3',
  code: 'multirest_missed',
  part_id: 'P1',
  measure_numbers: [3],
  page: 1,
  measure_id: 'm3',
  params: { count: 8 },
  choices: [
    { id: 'accept', label: 'rest_measures', params: { count: 8 }, input: null },
    { id: 'count', label: 'rest_other_count', params: {}, input: 'count' },
    { id: 'keep', label: 'rest_one_measure', params: {}, input: null },
  ],
  confidence: 0.6,
  issue_count: 1,
  image: 'data:image/png;base64,AAAA',
}

/** Question « quelle est cette note ? » : do6 ou do5. */
export const noteQuestion: Question = {
  key: 'note_position_mismatch:P1:n7',
  code: 'note_position_mismatch',
  part_id: 'P1',
  measure_numbers: [5],
  page: 2,
  measure_id: 'm5',
  params: {},
  choices: [
    { id: 'accept', label: 'note', params: { note: { step: 'C', octave: 6, alter: 0 } }, input: null },
    { id: 'keep', label: 'note', params: { note: { step: 'C', octave: 5, alter: 0 } }, input: null },
  ],
  confidence: 0.5,
  issue_count: 1,
  image: null,
}

export function questionsState(questions: Question[], extra: Partial<QuestionsState> = {}): QuestionsState {
  return { score_id: 1, questions, unasked: 0, checks: [], compared_parts: 0, answered: 0, can_undo: false, ...extra }
}

/** Faux pont : chaque méthode peut être remplacée par le test. */
export function fakeApi(overrides: Partial<PythonApi> = {}, info: AppInfo = fakeInfo): PythonApi {
  return {
    ping: async () => 'pong',
    get_app_info: async () => info,
    choose_file: async () => null,
    open_file: async () => ({ scores: [] }),
    get_progress: async () => ({ stage: null }),
    list_scores: async () => [],
    get_questions: async () => questionsState([]),
    answer_question: async () => questionsState([]),
    undo_answer: async () => questionsState([]),
    get_page: async () => ({ error: 'page_not_found' }),
    get_rendering: async () => ({ error: 'score_not_found' }),
    get_measure: async () => ({ error: 'edit_failed' }),
    edit_score: async () => ({ error: 'edit_failed' }),
    undo_edit: async () => ({ error: 'edit_failed' }),
    get_instruments: async () => [],
    get_score_instrument: async () => ({ instrument_id: null, variant_id: null, detected: true }),
    set_score_instrument: async () => ({ error: 'transposition_failed' }),
    check_transposition: async () => ({ error: 'transposition_failed' }),
    transpose_score: async () => ({ error: 'transposition_failed' }),
    get_export_options: async () => ({ default_name: 'Partition', musescore: true, questions: 0, checks: 0 }),
    choose_save_path: async () => null,
    export_score: async () => ({ error: 'write_failed' }),
    ...overrides,
  }
}
