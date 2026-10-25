/**
 * Ce que la lecture a remarqué sur une partition (moteur : library.reading_warnings) :
 * image de trop basse résolution, page qu'Audiveris n'a pas pu lire, page très penchée.
 * Chaque avertissement dit aussi quoi faire (rescanner à 300 dpi...).
 */
import { useTranslation } from 'react-i18next'

import type { ReadingWarning } from './bridge'

interface Props {
  warnings: ReadingWarning[]
}

export default function ReadingWarnings({ warnings }: Props) {
  const { t } = useTranslation()
  if (warnings.length === 0) return null
  return (
    <ul className="reading-warnings" aria-label={t('warnings.label')}>
      {warnings.map((warning) => (
        <li key={warning.code}>
          {t(`warnings.${warning.code}`, {
            count: warning.pages.length,
            pages: warning.pages.join(', '),
            dpi: warning.dpi,
          })}
        </li>
      ))}
    </ul>
  )
}
