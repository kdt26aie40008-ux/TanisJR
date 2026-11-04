import { useState } from 'react'
import { api, errorMessage } from '../api/client'
import { LANGUAGE_NAMES, type AppSettings, type LanguageCode, type ProfileEntry } from '../api/types'

const SELF_FIELDS = [
  {
    key: 'self.user_name',
    label: '呼んでほしい名前',
    placeholder: 'たろう',
    rows: 1,
  },
  {
    key: 'self.personality',
    label: 'あなたの個性（性格・価値観・好き嫌い）',
    placeholder: '負けず嫌い。曖昧なことが苦手。甘いものが好き。',
    rows: 3,
  },
  {
    key: 'self.traits',
    label: 'あなたの特徴（口ぐせ・話し方・生活のリズムなど）',
    placeholder: '「まあいいか」が口ぐせ。夜型で、朝は弱い。',
    rows: 3,
  },
] as const

type SelfKey = (typeof SELF_FIELDS)[number]['key']

interface Props {
  settings: AppSettings
  profile: ProfileEntry[]
  update: <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => void
  /** 設定（名前・言語・読み）を保存する */
  saveSettings: () => Promise<boolean>
  onProfileSaved: (entries: ProfileEntry[]) => void
}

/**
 * 設定「あなたのこと」。AI があなたに寄せて話すための情報で、
 * すべて入力すると「ねえ○○」で起きる機能が使えるようになる。
 */
export function SelfProfilePanel({ settings, profile, update, saveSettings, onProfileSaved }: Props) {
  const find = (key: string) => profile.find((e) => e.key === key)?.content ?? ''
  // 個性は、初回の質問「どんな性格で…」への答えを最初の案にする
  const [values, setValues] = useState<Record<SelfKey, string>>(() => ({
    'self.user_name': find('self.user_name'),
    'self.personality': find('self.personality') || find('setup.q2_personality'),
    'self.traits': find('self.traits'),
  }))
  const [feedback, setFeedback] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [saving, setSaving] = useState(false)

  const save = async () => {
    setSaving(true)
    setFeedback(null)
    try {
      const saved: ProfileEntry[] = []
      for (const field of SELF_FIELDS) {
        const value = values[field.key].trim()
        if (value && value !== find(field.key)) saved.push(await api.updateProfile(field.key, value))
      }
      if (saved.length) onProfileSaved(saved)
      if (!(await saveSettings())) return
      setFeedback({ kind: 'ok', text: '保存しました。' })
    } catch (err) {
      setFeedback({ kind: 'error', text: errorMessage(err) })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="panel">
      <h2>あなたのこと</h2>
      <p className="hint">
        {settings.ai_name} はこれをもとに、あなたに寄せて話します（二人目のあなたとして）。すべて入力すると「ねえ、
        {settings.ai_name}」と呼びかけて起こす機能が使えるようになります。内容は暗号化してこの PC にだけ保存されます。
      </p>
      <div className="form-row">
        <label className="field">
          <span>AI の名前</span>
          <input value={settings.ai_name} maxLength={32} onChange={(e) => update('ai_name', e.target.value)} />
        </label>
        <label className="field">
          <span>AI の名前の読み（ひらがな。漢字の名前を聞き取りやすくします）</span>
          <input
            value={settings.wake_reading}
            maxLength={32}
            placeholder="たにす"
            onChange={(e) => update('wake_reading', e.target.value)}
          />
        </label>
      </div>
      {SELF_FIELDS.map((field) => (
        <label className="field" key={field.key}>
          <span>{field.label}</span>
          {field.rows === 1 ? (
            <input
              value={values[field.key]}
              maxLength={64}
              placeholder={field.placeholder}
              onChange={(e) => setValues({ ...values, [field.key]: e.target.value })}
            />
          ) : (
            <textarea
              value={values[field.key]}
              rows={field.rows}
              maxLength={4000}
              placeholder={field.placeholder}
              onChange={(e) => setValues({ ...values, [field.key]: e.target.value })}
            />
          )}
        </label>
      ))}
      <label className="field">
        <span>言語（聞き取りと返事の言語）</span>
        <select value={settings.language} onChange={(e) => update('language', e.target.value as LanguageCode)}>
          {Object.entries(LANGUAGE_NAMES).map(([code, name]) => (
            <option key={code} value={code}>
              {name}
            </option>
          ))}
        </select>
      </label>
      {settings.language !== 'ja' && (
        <p className="warn-text">日本語以外では、声での返事（読み上げ）と口の動きは使えません（準備中）。文字と聞き取りは使えます。</p>
      )}
      <div className="actions">
        <button className="btn primary" onClick={() => void save()} disabled={saving}>
          {saving ? '保存中…' : '保存'}
        </button>
      </div>
      {feedback && (
        <p className={feedback.kind === 'ok' ? 'ok-text' : 'error-text'} role={feedback.kind === 'error' ? 'alert' : 'status'}>
          {feedback.text}
        </p>
      )}
    </div>
  )
}
