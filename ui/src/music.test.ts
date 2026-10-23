// Tests de l'écriture des valeurs musicales.

import { describe, expect, it } from 'vitest'

import { formatParams, isNote, noteName } from './music'

describe('noteName', () => {
  it('écrit les notes en solfège ou en lettres', () => {
    expect(noteName({ step: 'C', octave: 6 }, 'fr')).toBe('do6')
    expect(noteName({ step: 'F', octave: 4, alter: 1 }, 'fr')).toBe('fa♯4')
    expect(noteName({ step: 'B', octave: 3, alter: -1 }, 'en')).toBe('B♭3')
    expect(noteName({ step: 'D', octave: 5, alter: 0 }, 'en')).toBe('D5')
  })
})

describe('formatParams', () => {
  it('remplace les notes et les listes de notes par leurs noms', () => {
    const params = {
      note: { step: 'E', octave: 5, alter: -1 },
      notes: [
        { step: 'C', octave: 7, alter: 0 },
        { step: 'D', octave: 7, alter: 0 },
      ],
      count: 3,
      time: '3/4',
    }
    expect(formatParams(params, 'fr')).toEqual({ note: 'mi♭5', notes: 'do7, ré7', count: 3, time: '3/4' })
  })

  it('reconnaît une note', () => {
    expect(isNote({ step: 'C', octave: 4 })).toBe(true)
    expect(isNote({ step: 'C' })).toBe(false)
    expect(isNote(null)).toBe(false)
  })
})
