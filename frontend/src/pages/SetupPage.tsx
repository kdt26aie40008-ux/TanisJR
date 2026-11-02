import { useEffect, useRef, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { SetupQuestionsResponse } from '../api/types'
import { suggestAiName } from '../lib/aiName'

type Step = { kind: 'consent' } | { kind: 'question'; index: number } | { kind: 'confirm' }

const MAX_ANSWER = 4000

export function SetupPage({ onComplete }: { onComplete: (aiName: string) => void }) {
  const [data, setData] = useState<SetupQuestionsResponse | null>(null)
  const [loadError, setLoadError] = useState('')
  const [step, setStep] = useState<Step>({ kind: 'consent' })
  const [consent, setConsent] = useState(false)
  const [answers, setAnswers] = useState<string[]>(['', '', ''])
  const [draft, setDraft] = useState('')
  const [aiName, setAiName] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    api.setupQuestions().then(setData, (err) => setLoadError(errorMessage(err)))
  }, [])

  useEffect(() => {
    if (step.kind === 'question') inputRef.current?.focus()
  }, [step])

  if (loadError) return <div className="center-screen"><div className="panel error-panel" role="alert">{loadError}</div></div>
  if (!data) return <div className="center-screen">読み込み中…</div>

  const questions = data.questions

  const goToQuestion = (index: number) => {
    setDraft(answers[index])
    setStep({ kind: 'question', index })
    setError('')
  }

  const submitAnswer = (index: number) => {
    const value = draft.trim()
    if (!value) {
      setError('回答を入力してください。')
      return
    }
    const next = answers.map((a, i) => (i === index ? value : a))
    setAnswers(next)
    setError('')
    if (index < questions.length - 1) {
      setDraft(next[index + 1])
      setStep({ kind: 'question', index: index + 1 })
    } else {
      setAiName(suggestAiName(value))
      setStep({ kind: 'confirm' })
    }
  }

  const save = async () => {
    const name = aiName.trim()
    if (!name) {
      setError('AIの名前を入力してください。')
      return
    }
    setSaving(true)
    setError('')
    try {
      const result = await api.completeSetup({ consent, answers, ai_name: name })
      onComplete(result.ai_name)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="setup">
      <div className="setup-card panel">
        <header className="setup-header">
          <span className="brand-mark" aria-hidden>
            ◆
          </span>
          <h1>初回設定</h1>
          <ol className="steps" aria-label="進行状況">
            <li className={step.kind === 'consent' ? 'current' : 'done'}>同意</li>
            {questions.map((_, i) => (
              <li
                key={i}
                className={
                  step.kind === 'question' && step.index === i
                    ? 'current'
                    : step.kind === 'confirm' || (step.kind === 'question' && step.index > i)
                      ? 'done'
                      : ''
                }
              >
                質問{i + 1}
              </li>
            ))}
            <li className={step.kind === 'confirm' ? 'current' : ''}>確認</li>
          </ol>
        </header>

        {step.kind === 'consent' && (
          <section aria-labelledby="consent-title">
            <h2 id="consent-title">保存する情報と利用目的</h2>
            <p>{data.consent.purpose}</p>
            <h3>保存する内容</h3>
            <ul>
              {data.consent.stored_items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <h3>取り扱いについて</h3>
            <ul>
              {data.consent.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
            <label className="checkbox">
              <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              上記の内容を確認し、保存に同意します
            </label>
            <p className="hint">同意しない場合、プロフィールは保存されず、利用を開始できません。</p>
            <div className="actions">
              <button className="btn primary" disabled={!consent} onClick={() => goToQuestion(0)}>
                同意して始める
              </button>
            </div>
          </section>
        )}

        {step.kind === 'question' && (
          <section className="setup-chat">
            {questions.slice(0, step.index).map((q, i) => (
              <div key={q.key}>
                <div className="bubble ai">{q.text}</div>
                <div className="bubble user">{answers[i]}</div>
              </div>
            ))}
            <div className="bubble ai" data-testid="current-question">
              {questions[step.index].text}
            </div>
            <form
              className="composer"
              onSubmit={(e) => {
                e.preventDefault()
                submitAnswer(step.index)
              }}
            >
              <label className="sr-only" htmlFor="setup-answer">
                回答
              </label>
              <textarea
                id="setup-answer"
                ref={inputRef}
                value={draft}
                maxLength={MAX_ANSWER}
                rows={step.index === 1 ? 6 : 3}
                placeholder="ここに回答を入力"
                onChange={(e) => setDraft(e.target.value)}
              />
              <div className="actions">
                <button
                  type="button"
                  className="btn"
                  onClick={() => (step.index === 0 ? setStep({ kind: 'consent' }) : goToQuestion(step.index - 1))}
                >
                  戻る
                </button>
                <button type="submit" className="btn primary">
                  次へ
                </button>
              </div>
            </form>
          </section>
        )}

        {step.kind === 'confirm' && (
          <section aria-labelledby="confirm-title">
            <h2 id="confirm-title">内容の確認</h2>
            <dl className="summary">
              {questions.map((q, i) => (
                <div key={q.key}>
                  <dt>{q.text}</dt>
                  <dd>{answers[i]}</dd>
                </div>
              ))}
            </dl>
            <label className="field">
              <span>AIの名前（回答から読み取った候補です。必要なら修正してください）</span>
              <input value={aiName} maxLength={32} onChange={(e) => setAiName(e.target.value)} />
            </label>
            <div className="actions">
              <button className="btn" onClick={() => goToQuestion(questions.length - 1)} disabled={saving}>
                戻る
              </button>
              <button className="btn primary" onClick={() => void save()} disabled={saving}>
                {saving ? '保存中…' : 'この内容で保存して始める'}
              </button>
            </div>
          </section>
        )}

        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  )
}
