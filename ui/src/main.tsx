// Point d'entrée de l'interface : affiche le composant App dans la page.

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import './i18n'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
