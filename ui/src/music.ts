// Écriture des valeurs musicales pour l'affichage (noms de notes, listes...).

import type { Language } from './i18n'

/** Une note telle que le moteur la décrit. */
export interface NoteValue {
  step: string
  octave: number
  alter?: number
}

/** Noms des notes en français (solfège) ; en anglais, la lettre suffit. */
const FRENCH_STEPS: Record<string, string> = {
  C: 'do',
  D: 'ré',
  E: 'mi',
  F: 'fa',
  G: 'sol',
  A: 'la',
  B: 'si',
}

const ALTERATIONS: Record<number, string> = { [-2]: '𝄫', [-1]: '♭', 0: '', 1: '♯', 2: '𝄪' }

/**
 * Nom d'une note avec son octave : « do♯5 » en français, « C♯5 » en anglais.
 * L'octave suit la numérotation internationale (do4 = le do du milieu du piano),
 * la même que celle du moteur.
 */
export function noteName(note: NoteValue, language: Language): string {
  const step = language === 'fr' ? (FRENCH_STEPS[note.step] ?? note.step) : note.step
  return `${step}${ALTERATIONS[note.alter ?? 0] ?? ''}${note.octave}`
}

/** Vrai si la valeur ressemble à une note du moteur. */
export function isNote(value: unknown): value is NoteValue {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as NoteValue).step === 'string' &&
    typeof (value as NoteValue).octave === 'number'
  )
}

/**
 * Prépare les valeurs d'une question pour la traduction : les notes deviennent leur nom,
 * les listes de notes une suite de noms séparés par des virgules.
 */
export function formatParams(
  params: Record<string, unknown>,
  language: Language,
): Record<string, unknown> {
  const result: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(params)) {
    if (isNote(value)) {
      result[key] = noteName(value, language)
    } else if (Array.isArray(value) && value.every(isNote)) {
      result[key] = value.map((note) => noteName(note, language)).join(', ')
    } else {
      result[key] = value
    }
  }
  return result
}
