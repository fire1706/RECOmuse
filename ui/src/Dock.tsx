/**
 * Panneau repliable de l'onglet Partition (questions, scan), comme les panneaux de
 * MuseScore 4 : un en-tête avec son nom et un bouton pour le replier. Replié, il ne
 * reste qu'une fine bande verticale avec son nom, qui le rouvre.
 */
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { ChevronIcon } from './Icons'

interface Props {
  id: string // sert aussi au nom de classe (dock-<id>) et au titre (<id>-title)
  title: string
  open: boolean
  onToggle: () => void
  children: ReactNode
}

export default function Dock({ id, title, open, onToggle, children }: Props) {
  const { t } = useTranslation()
  const label = t(open ? 'panels.hide' : 'panels.show', { name: title })
  return (
    <section className={`dock dock-${id}${open ? '' : ' collapsed'}`}
      aria-labelledby={`${id}-title`}>
      <div className="dock-header">
        <h2 id={`${id}-title`}>{title}</h2>
        <button type="button" className="dock-toggle" onClick={onToggle} aria-expanded={open}
          aria-label={label} title={label}>
          <ChevronIcon open={open} />
        </button>
      </div>
      {open && <div className="dock-body">{children}</div>}
    </section>
  )
}
