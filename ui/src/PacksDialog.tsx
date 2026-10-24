// Fenêtre « Packs d'apprentissage » : partager ce que RECOmuse a appris avec les autres
// membres de la fanfare (un fichier à envoyer), et importer les packs reçus.
// Un pack ne contient ni images ni partitions : seulement des réponses et des corrections.

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { isError, type PackInfo, type PythonApi } from './bridge'

interface PacksDialogProps {
  api: PythonApi
  onClose: () => void
  /** Après un import ou un retrait : les règles apprises ont pu changer. */
  onChanged?: () => void
}

export default function PacksDialog({ api, onClose, onChanged }: PacksDialogProps) {
  const { t, i18n } = useTranslation()
  const [packs, setPacks] = useState<PackInfo[] | null>(null)
  const [author, setAuthor] = useState('')
  const [includeScores, setIncludeScores] = useState(true)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    api
      .list_packs()
      .then((value) => !cancelled && setPacks(value))
      .catch(() => !cancelled && setError('unexpected'))
    return () => {
      cancelled = true
    }
  }, [api])

  const date = (text: string) => {
    const parsed = new Date(text)
    return Number.isNaN(parsed.getTime()) ? text : parsed.toLocaleDateString(i18n.resolvedLanguage)
  }

  /** Lance une action ; les erreurs du moteur s'affichent. */
  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      await action()
    } catch {
      setError('unexpected')
    } finally {
      setBusy(false)
    }
  }

  const exportPack = () =>
    run(async () => {
      const name = `RECOmuse - ${author.trim() || new Date().toISOString().slice(0, 10)}`
      const path = await api.choose_pack_file(true, t('packs.filter'), name)
      if (!path) return
      const result = await api.export_pack(path, author, includeScores)
      if (isError(result)) setError(result.error)
      else setMessage(t('packs.exported', { path: result.path, answers: t('packs.answers', { count: result.answers }), scores: t('packs.scores', { count: result.scores }) }))
    })

  const importPack = () =>
    run(async () => {
      const path = await api.choose_pack_file(false, t('packs.filter'), '')
      if (!path) return
      const result = await api.import_pack(path)
      if (isError(result)) {
        setError(result.error)
        return
      }
      setPacks(await api.list_packs())
      setMessage(t('packs.imported', { author: result.author ?? t('packs.anonymous') }))
      onChanged?.()
    })

  const removePack = (pack: PackInfo) =>
    run(async () => {
      const result = await api.remove_pack(pack.id)
      if (isError(result)) setError(result.error)
      else {
        setPacks(result.packs)
        onChanged?.()
      }
    })

  return (
    <div className="dialog-backdrop" role="presentation" onClick={onClose}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="packs-title"
        onClick={(e) => e.stopPropagation()}>
        <h2 id="packs-title">{t('packs.title')}</h2>
        <p className="question-note">{t('packs.explanation')}</p>

        <fieldset>
          <legend>{t('packs.share')}</legend>
          <label>
            {t('packs.author')}
            <input type="text" value={author} maxLength={60} disabled={busy}
              onChange={(e) => setAuthor(e.target.value)} />
          </label>
          <label className="radio">
            <input type="checkbox" checked={includeScores} disabled={busy}
              onChange={(e) => setIncludeScores(e.target.checked)} />
            {t('packs.includeScores')}
          </label>
          <div>
            <button type="button" className="primary" disabled={busy} onClick={exportPack}>
              {t('packs.create')}
            </button>
          </div>
        </fieldset>

        <fieldset>
          <legend>{t('packs.received')}</legend>
          <div>
            <button type="button" disabled={busy} onClick={importPack}>{t('packs.import')}</button>
          </div>
          {packs !== null && packs.length === 0 && <p className="empty">{t('packs.none')}</p>}
          {packs !== null && packs.length > 0 && (
            <ul className="rules">
              {packs.map((pack) => (
                <li key={pack.id}>
                  <span>
                    {t('packs.item', {
                      author: pack.author ?? t('packs.anonymous'),
                      date: date(pack.created_at),
                      answers: t('packs.answers', { count: pack.answers }),
                      scores: t('packs.scores', { count: pack.scores }),
                    })}
                  </span>{' '}
                  <button type="button" className="link-button" disabled={busy} onClick={() => removePack(pack)}>
                    {t('packs.remove')}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </fieldset>

        {message && <p role="status" className="transpose-preview">{message}</p>}
        {error && <p className="error">{t(`errors.${error}`, { defaultValue: t('errors.unexpected') })}</p>}
        <div className="dialog-actions">
          <button type="button" onClick={onClose}>{t('packs.close')}</button>
        </div>
      </div>
    </div>
  )
}
