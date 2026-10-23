// Préparation commune à tous les tests de l'interface.

import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

import './i18n'

// Vide la page entre deux tests.
afterEach(() => {
  cleanup()
})
