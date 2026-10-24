// Fenêtre « Règles apprises » : ce que le logiciel répond désormais tout seul, parce que
// l'utilisateur a toujours répondu ainsi à des questions semblables. Chaque règle peut
// être désactivée (la question sera de nouveau posée).

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { isError, type PythonApi, type Rule } from './bridge'

interface RulesDialogProps {
  api: PythonApi
  onClose: () => void
}

type Translate = ReturnType<typeof useTranslation>['t']

/** Ce que décrit la signature d'une règle : « note lue au-dessus de la portée… ». */
export function ruleContext(rule: Rule, t: Translate): string {
  const { code, ...context } = rule.signature
  const values: Record<string, string> = {}
  for (const [key, value] of Object.entries(context)) {
    values[key] = t(`rules.values.${key}.${String(value)}`, { defaultValue: String(value) })
  }
  return t(`rules.contexts.${code}`, { ...values, defaultValue: t(`rules.contexts.other`, { code }) })
}

/** La réponse que la règle donne : « prendre la note d'après sa position ». */
export function ruleAnswer(rule: Rule, t: Translate): string {
  return t(`rules.answers.${rule.signature.code}.${rule.choice_id}`, {
    defaultValue: t(`rules.answers.default.${rule.choice_id}`, { defaultValue: rule.choice_id }),
  })
}

export default function RulesDialog({ api, onClose }: RulesDialogProps) {
  const { t } = useTranslation()
  const [rules, setRules] = useState<Rule[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .get_rules()
      .then((value) => !cancelled && setRules(value))
      .catch(() => !cancelled && setError('unexpected'))
    return () => {
      cancelled = true
    }
  }, [api])

  async function toggle(rule: Rule) {
    const result = await api.set_rule_enabled(rule.key, !rule.enabled)
    if (isError(result)) setError(result.error)
    else setRules(result.rules)
  }

  return (
    <div className="dialog-backdrop" role="presentation" onClick={onClose}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="rules-title"
        onClick={(e) => e.stopPropagation()}>
        <h2 id="rules-title">{t('rules.title')}</h2>
        <p className="question-note">{t('rules.explanation')}</p>
        {rules === null && !error && <p className="empty">{t('rules.loading')}</p>}
        {rules !== null && rules.length === 0 && <p className="empty">{t('rules.none')}</p>}
        {rules !== null && rules.length > 0 && (
          <ul className="rules">
            {rules.map((rule) => (
              <li key={rule.key} className={rule.enabled ? '' : 'disabled'}>
                <label>
                  <input type="checkbox" checked={rule.enabled} onChange={() => toggle(rule)} />
                  <span>
                    <strong>{ruleContext(rule, t)}</strong> → {ruleAnswer(rule, t)}
                    <br />
                    <small>
                      {t('rules.evidence', { count: rule.evidence, agreeing: rule.agreeing })}
                      {rule.from_packs > 0 && ` ${t('rules.fromPacks', { count: rule.from_packs })}`}
                    </small>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
        {error && <p className="error">{t(`errors.${error}`, { defaultValue: t('errors.unexpected') })}</p>}
        <div className="dialog-actions">
          <button type="button" onClick={onClose}>{t('rules.close')}</button>
        </div>
      </div>
    </div>
  )
}
