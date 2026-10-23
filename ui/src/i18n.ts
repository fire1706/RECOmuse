// Traductions de l'interface (français et anglais).
//
// Aucun texte n'est écrit en dur dans les composants : ils utilisent des clés
// (ex. t('panels.scan')) dont le texte se trouve dans locales/fr.json et locales/en.json.
// Pour ajouter un texte : ajouter la même clé dans LES DEUX fichiers
// (un test vérifie qu'ils ont exactement les mêmes clés).

import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import en from './locales/en.json'
import fr from './locales/fr.json'

export const SUPPORTED_LANGUAGES = ['fr', 'en'] as const
export type Language = (typeof SUPPORTED_LANGUAGES)[number]

/** Langue par défaut : la fanfare est francophone. */
export const DEFAULT_LANGUAGE: Language = 'fr'

/**
 * Choisit la langue de départ à partir de celle du système (ex. « en-GB » → « en »).
 * Toute langue non prise en charge (néerlandais, allemand…) donne le français.
 */
export function detectLanguage(systemLanguage: string | undefined): Language {
  const code = (systemLanguage ?? '').slice(0, 2).toLowerCase()
  return (SUPPORTED_LANGUAGES as readonly string[]).includes(code)
    ? (code as Language)
    : DEFAULT_LANGUAGE
}

i18n.use(initReactI18next).init({
  resources: {
    fr: { translation: fr },
    en: { translation: en },
  },
  lng: detectLanguage(typeof navigator === 'undefined' ? undefined : navigator.language),
  fallbackLng: DEFAULT_LANGUAGE,
  interpolation: {
    // React protège déjà l'affichage contre l'injection de HTML.
    escapeValue: false,
  },
})

export default i18n
