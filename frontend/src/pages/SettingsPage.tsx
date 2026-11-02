import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { AppSettings, CatalogModel, ModelStatus, ProfileEntry } from '../api/types'
import { BackupCreate, BackupRestore } from '../components/BackupPanel'
import { ModelDownloadDialog } from '../components/ModelDownloadDialog'
import { VoiceSettings } from '../components/VoiceSettings'

type Feedback = { kind: 'ok' | 'error'; text: string } | null

interface Props {
  onAiNameChange: (name: string) => void
  onRestored: () => void
}

export function SettingsPage({ onAiNameChange, onRestored }: Props) {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [profile, setProfile] = useState<ProfileEntry[]>([])
  const [models, setModels] = useState<ModelStatus | null>(null)
  const [loadError, setLoadError] = useState('')
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [saving, setSaving] = useState(false)
  const [downloading, setDownloading] = useState<CatalogModel | null>(null)

  const loadModels = useCallback(async () => {
    try {
      setModels(await api.modelStatus())
    } catch (err) {
      setLoadError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    Promise.all([api.getSettings(), api.getProfile()]).then(
      ([s, p]) => {
        setSettings(s)
        setProfile(p)
      },
      (err) => setLoadError(errorMessage(err)),
    )
    void loadModels()
  }, [loadModels])

  if (loadError && !settings) {
    return (
      <section className="page">
        <h1>設定</h1>
        <div className="banner error" role="alert">
          {loadError}
        </div>
      </section>
    )
  }
  if (!settings) return <section className="page">読み込み中…</section>

  const installed = models?.installed.map((m) => m.name) ?? []
  const embeddingNames = new Set(models?.catalog.filter((m) => m.kind === 'embedding').map((m) => m.name) ?? [])
  const chatInstalled = installed.filter((name) => !embeddingNames.has(name) && !name.includes('embed'))
  const modelOptions = Array.from(new Set([settings.model, ...chatInstalled]))
  const embeddingOptions = Array.from(new Set([settings.embedding_model, ...embeddingNames]))

  const update = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) =>
    setSettings((prev) => (prev ? { ...prev, [key]: value } : prev))

  const save = async () => {
    setSaving(true)
    setFeedback(null)
    try {
      // アバターの選択と利用規約の確認状態は、それぞれ専用の操作でのみ変更する
      const { avatar_id: _avatar, tts_acknowledged_speakers: _acks, ...values } = settings
      const saved = await api.updateSettings(values)
      setSettings(saved)
      onAiNameChange(saved.ai_name)
      setFeedback({ kind: 'ok', text: '設定を保存しました。' })
    } catch (err) {
      setFeedback({ kind: 'error', text: errorMessage(err) })
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="page settings-page">
      <h1>設定</h1>

      <div className="panel">
        <h2>基本設定</h2>
        <label className="field">
          <span>AIの名前</span>
          <input value={settings.ai_name} maxLength={32} onChange={(e) => update('ai_name', e.target.value)} />
        </label>
        <label className="field">
          <span>使用モデル</span>
          <select value={settings.model} onChange={(e) => update('model', e.target.value)}>
            {modelOptions.map((name) => (
              <option key={name} value={name}>
                {name}
                {installed.includes(name) ? '' : '（未インストール）'}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>代替モデル（GPUメモリ不足時、CPU実行でも失敗した場合に使用）</span>
          <select value={settings.fallback_model} onChange={(e) => update('fallback_model', e.target.value)}>
            <option value="">使用しない</option>
            {chatInstalled
              .filter((name) => name !== settings.model)
              .map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
          </select>
        </label>
        <label className="field">
          <span>
            応答の多様性（temperature）: <strong>{settings.temperature.toFixed(1)}</strong>
          </span>
          <input
            type="range"
            min={0}
            max={1.5}
            step={0.1}
            value={settings.temperature}
            onChange={(e) => update('temperature', Number(e.target.value))}
          />
        </label>
        <label className="field">
          <span>会話の記憶範囲（コンテキスト長）</span>
          <select value={settings.num_ctx} onChange={(e) => update('num_ctx', Number(e.target.value))}>
            <option value={2048}>2048（省メモリ）</option>
            <option value={4096}>4096（標準）</option>
            <option value={8192}>8192（GPUメモリを多く使用）</option>
          </select>
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={settings.think} onChange={(e) => update('think', e.target.checked)} />
          思考モード（回答前にじっくり考える。応答は遅くなります）
        </label>

        <h3>記憶</h3>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={settings.save_conversations_default}
            onChange={(e) => update('save_conversations_default', e.target.checked)}
          />
          新しい会話を最初から「保存する」にする
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={settings.auto_extract} onChange={(e) => update('auto_extract', e.target.checked)} />
          保存した会話から記憶を自動で抽出する（個人情報・性格・価値観は承認後に保存）
        </label>
        <label className="field">
          <span>記憶検索用モデル（変更すると索引を作り直します）</span>
          <select value={settings.embedding_model} onChange={(e) => update('embedding_model', e.target.value)}>
            {embeddingOptions.map((name) => (
              <option key={name} value={name}>
                {name}
                {installed.includes(name) ? '' : '（未インストール）'}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>1回の応答で参照する記憶の最大数（0で参照しない）</span>
          <input
            type="number"
            min={0}
            max={20}
            value={settings.rag_max_results}
            onChange={(e) => update('rag_max_results', Math.max(0, Math.min(20, Number(e.target.value) || 0)))}
          />
        </label>
        <label className="field">
          <span>
            関連度のしきい値: <strong>{settings.rag_max_distance.toFixed(2)}</strong>
            （小さいほど、関係が強い記憶だけを参照）
          </span>
          <input
            type="range"
            min={0.2}
            max={0.8}
            step={0.05}
            value={settings.rag_max_distance}
            onChange={(e) => update('rag_max_distance', Number(e.target.value))}
          />
        </label>

        <VoiceSettings settings={settings} update={update} />
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

      <div className="panel">
        <h2>プロフィール</h2>
        <p className="hint">初回設定で入力した内容です。AIはこの情報をもとにあなたを理解します。</p>
        {profile.map((entry) => (
          <ProfileEditor
            key={entry.key}
            entry={entry}
            onSaved={(saved) => setProfile((prev) => prev.map((p) => (p.key === saved.key ? saved : p)))}
          />
        ))}
      </div>

      <div className="panel">
        <h2>モデル管理</h2>
        {!models ? (
          <p>確認中…</p>
        ) : !models.ollama_available ? (
          <div className="banner error" role="alert">
            {models.message}
          </div>
        ) : (
          <div className="table-scroll">
          <table className="model-table">
            <thead>
              <tr>
                <th>モデル</th>
                <th>用途</th>
                <th>容量</th>
                <th>説明</th>
                <th>状態</th>
              </tr>
            </thead>
            <tbody>
              {models.catalog.map((m) => (
                <tr key={m.name}>
                  <td>{m.name}</td>
                  <td>{m.kind === 'embedding' ? '記憶検索' : '会話'}</td>
                  <td>約{m.size_gb}GB</td>
                  <td>{m.description}</td>
                  <td>
                    {installed.includes(m.name) ? (
                      <span className="ok-text">導入済み</span>
                    ) : (
                      <button className="btn small" onClick={() => setDownloading(m)}>
                        ダウンロード
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </div>

      <div className="panel">
        <h2>データ保護</h2>
        <p className="hint">
          保存データ（プロフィール・記憶・会話）は暗号化され、暗号鍵はこのPCのWindowsアカウントで保護されています。
          PCの故障や買い替えに備えて、定期的にバックアップを作成してください。
        </p>
        <BackupCreate />
        <hr className="divider" />
        <BackupRestore onRestored={onRestored} />
      </div>

      {downloading && models && (
        <ModelDownloadDialog
          model={downloading}
          status={models}
          onClose={() => {
            setDownloading(null)
            void loadModels()
          }}
        />
      )}
    </section>
  )
}

function ProfileEditor({ entry, onSaved }: { entry: ProfileEntry; onSaved: (e: ProfileEntry) => void }) {
  const [value, setValue] = useState(entry.content)
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [saving, setSaving] = useState(false)
  const dirty = value.trim() !== entry.content

  const save = async () => {
    setSaving(true)
    setFeedback(null)
    try {
      const saved = await api.updateProfile(entry.key, value)
      onSaved(saved)
      setValue(saved.content)
      setFeedback({ kind: 'ok', text: '保存しました。' })
    } catch (err) {
      setFeedback({ kind: 'error', text: errorMessage(err) })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="profile-entry">
      <label className="field">
        <span>{entry.question ?? entry.key}</span>
        <textarea value={value} rows={3} maxLength={4000} onChange={(e) => setValue(e.target.value)} />
      </label>
      <div className="profile-meta">
        <span className="hint">更新: {new Date(entry.updated_at).toLocaleString('ja-JP')}</span>
        <button className="btn small" onClick={() => void save()} disabled={!dirty || saving}>
          保存
        </button>
      </div>
      {feedback && <p className={feedback.kind === 'ok' ? 'ok-text' : 'error-text'}>{feedback.text}</p>}
    </div>
  )
}
