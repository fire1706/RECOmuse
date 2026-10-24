/**
 * Petites icônes de la barre d'outils et des panneaux, dessinées en SVG (aucune
 * bibliothèque à installer). Elles prennent la couleur du texte qui les entoure
 * (currentColor) et sont décoratives : le texte du bouton dit ce qu'il fait.
 */
import type { ReactNode } from 'react'

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
      fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
      strokeLinejoin="round">
      {children}
    </svg>
  )
}

/** Dossier ouvert : ouvrir une partition. */
export const OpenIcon = () => (
  <Icon>
    <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1" />
    <path d="M3 7v11a1 1 0 0 0 1 1h14.5a1 1 0 0 0 1-.8L21.5 11H7.4a1 1 0 0 0-1 .8L4.3 19" />
  </Icon>
)

/** Flèche qui sort d'un plateau : exporter. */
export const ExportIcon = () => (
  <Icon>
    <path d="M12 15V3" />
    <path d="m7 8 5-5 5 5" />
    <path d="M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6" />
  </Icon>
)

/** Deux flèches, vers le haut et vers le bas : transposer. */
export const TransposeIcon = () => (
  <Icon>
    <path d="M8 20V4" />
    <path d="m4 8 4-4 4 4" />
    <path d="M16 4v16" />
    <path d="m12 16 4 4 4-4" />
  </Icon>
)

/** Portées empilées : conducteur. */
export const ConductorIcon = () => (
  <Icon>
    <path d="M4 5h16M4 8h16" />
    <path d="M4 12h16M4 15h16" />
    <path d="M4 19h16" />
  </Icon>
)

/** Liste cochée : règles apprises. */
export const RulesIcon = () => (
  <Icon>
    <path d="m4 6 1.5 1.5L8 5" />
    <path d="m4 12 1.5 1.5L8 11" />
    <path d="m4 18 1.5 1.5L8 17" />
    <path d="M11 6h9M11 12h9M11 18h9" />
  </Icon>
)

/** Paquet : packs d'apprentissage. */
export const PacksIcon = () => (
  <Icon>
    <path d="M21 8 12 3 3 8v8l9 5 9-5V8Z" />
    <path d="m3 8 9 5 9-5" />
    <path d="M12 13v8" />
  </Icon>
)

/** Note de musique : une partie. */
export const NoteIcon = () => (
  <Icon>
    <path d="M9 18V5l11-2v13" />
    <circle cx="6" cy="18" r="3" />
    <circle cx="17" cy="16" r="3" />
  </Icon>
)

/** Chevron vers la gauche (replier) ou la droite (déplier). */
export const ChevronIcon = ({ open }: { open: boolean }) => (
  <Icon>
    <path d={open ? 'm15 6-6 6 6 6' : 'm9 6 6 6-6 6'} />
  </Icon>
)
