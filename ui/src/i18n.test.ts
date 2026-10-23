// Tests des traductions : les deux langues doivent rester complètes et synchronisées.

import { describe, expect, it } from 'vitest'

import { detectLanguage } from './i18n'
import en from './locales/en.json'
import fr from './locales/fr.json'

/** Liste toutes les clés d'un fichier de traduction, ex. « panels.scan ». */
function flattenKeys(obj: object, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([key, value]) =>
    typeof value === 'object' && value !== null
      ? flattenKeys(value, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  )
}

describe('fichiers de traduction', () => {
  it('le français et l’anglais ont exactement les mêmes clés', () => {
    expect(flattenKeys(en).sort()).toEqual(flattenKeys(fr).sort())
  })

  it('aucun texte n’est vide', () => {
    for (const translations of [fr, en]) {
      const values = flattenKeys(translations).map((key) =>
        key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown>)[part], translations),
      )
      for (const value of values) {
        expect(typeof value === 'string' && value.trim().length > 0).toBe(true)
      }
    }
  })
})

describe('detectLanguage', () => {
  it('reconnaît le français et l’anglais', () => {
    expect(detectLanguage('fr-BE')).toBe('fr')
    expect(detectLanguage('en-GB')).toBe('en')
    expect(detectLanguage('EN')).toBe('en')
  })

  it('se rabat sur le français pour les autres langues', () => {
    expect(detectLanguage('nl-BE')).toBe('fr')
    expect(detectLanguage('de')).toBe('fr')
    expect(detectLanguage('')).toBe('fr')
    expect(detectLanguage(undefined)).toBe('fr')
  })
})
