// Écran principal de RECOmuse.
//
// Disposition prévue par le cahier des charges :
//   à gauche le scan d'origine, au centre les questions, à droite le rendu Verovio.
// Pour l'instant (tâche 2), les trois zones sont vides : elles seront remplies
// aux tâches 8 (questions) et 9 (vue côte à côte).

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { type AppInfo, type PythonApi, waitForBridge } from './bridge'
import { SUPPORTED_LANGUAGES } from './i18n'
import './App.css'

/** État de la connexion au moteur Python. */
type EngineState =
  | { kind: 'connecting' }
  | { kind: 'connected'; info: AppInfo }
  | { kind: 'unavailable' }

interface AppProps {
  /** Permet aux tests de fournir un faux pont ; par défaut, le vrai pont pywebview. */
  connect?: () => Promise<PythonApi | null>
}

export default function App({ connect = waitForBridge }: AppProps) {
  const { t, i18n } = useTranslation()
  const [engine, setEngine] = useState<EngineState>({ kind: 'connecting' })

  useEffect(() => {
    // « cancelled » évite de modifier l'écran s'il a été fermé entre-temps.
    let cancelled = false
    connect()
      .then(async (api) => {
        const info = api ? await api.get_app_info() : null
        if (!cancelled) {
          setEngine(info ? { kind: 'connected', info } : { kind: 'unavailable' })
        }
      })
      .catch(() => {
        if (!cancelled) setEngine({ kind: 'unavailable' })
      })
    return () => {
      cancelled = true
    }
  }, [connect])

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>{t('app.title')}</h1>
          <p className="tagline">{t('app.tagline')}</p>
        </div>
        <label className="language-picker">
          {t('language.label')}
          <select value={i18n.resolvedLanguage} onChange={(e) => i18n.changeLanguage(e.target.value)}>
            {SUPPORTED_LANGUAGES.map((lang) => (
              <option key={lang} value={lang}>
                {lang.toUpperCase()}
              </option>
            ))}
          </select>
        </label>
      </header>

      <main className="panels">
        <section className="panel" aria-labelledby="panel-scan">
          <h2 id="panel-scan">{t('panels.scan')}</h2>
          <p className="empty">{t('panels.scanEmpty')}</p>
        </section>
        <section className="panel panel-questions" aria-labelledby="panel-questions">
          <h2 id="panel-questions">{t('panels.questions')}</h2>
          <p className="empty">{t('panels.questionsEmpty')}</p>
        </section>
        <section className="panel" aria-labelledby="panel-result">
          <h2 id="panel-result">{t('panels.result')}</h2>
          <p className="empty">{t('panels.resultEmpty')}</p>
        </section>
      </main>

      <footer className="status-bar" role="status">
        {engine.kind === 'connecting' && t('status.connecting')}
        {engine.kind === 'unavailable' && t('status.noBridge')}
        {engine.kind === 'connected' && (
          <>
            {t('status.connected', {
              version: engine.info.version,
              python: engine.info.python_version,
            })}
            {' · '}
            {t('status.corrections', { count: engine.info.correction_count })}
          </>
        )}
      </footer>
    </div>
  )
}
