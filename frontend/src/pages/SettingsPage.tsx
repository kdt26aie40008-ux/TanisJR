import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { AppSettings, CatalogModel, ModelStatus, ProfileEntry } from '../api/types'
import { BackupCreate, BackupRestore } from '../components/BackupPanel'
import { BehaviorSettings } from '../components/BehaviorSettings'
import { InstallPanel } from '../components/InstallPanel'
import { ProactiveSettings, WakeSettings } from '../components/AssistantSettings'
import { SelfProfilePanel } from '../components/SelfProfilePanel'
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

  /** 設定を保存する。失敗したらメッセージを表示して false を返す */
  const saveSettings = async (): Promise<boolean> => {
    try {
      // アバターの選択・利用規約の確認状態・呼びかけ機能のオンオフは、それぞれ専用の操作でのみ変更する
      const { avatar_id: _avatar, tts_acknowledged_speakers: _acks, wake_enabled: _wake, ...values } = settings
      const saved = await api.updateSettings(values)
      setSettings(saved)
      onAiNameChange(saved.ai_name)
      return true
    } catch (err) {
      setFeedback({ kind: 'error', text: errorMessage(err) })
      return false
    }
  }

  const save = async () => {
    setSaving(true)
    setFeedback(null)
    if (await saveSettings()) setFeedback({ kind: 'ok', text: '設定を保存しました。' })
    setSaving(false)
  }

  return (
    <section className="page settings-page">
      <h1>設定</h1>

      <SelfProfilePanel
        settings={settings}
        profile={profile}
        update={update}
        saveSettings={saveSettings}
        onProfileSaved={(entries) =>
          setProfile((prev) => [...prev.filter((p) => !entries.some((e) => e.key === p.key)), ...entries])
        }
      />

      <div className="panel">
        <h2>会話</h2>
        <h3>思い出</h3>
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
          保存した会話から、あなたのことを自動で覚える（個人情報・性格・価値観は、あなたが承認してから覚えます）
        </label>

        <VoiceSettings settings={settings} update={update} />

        <h3>ふるまい</h3>
        <p className="hint">会話をより自然にするための動きです。1つずつオン・オフできます。</p>
        <BehaviorSettings settings={settings} update={update} />

        <h3>自分から話しかける</h3>
        <ProactiveSettings settings={settings} update={update} />

        <h3>「ねえ、{settings.ai_name}」で起きる</h3>
        <WakeSettings
          aiName={settings.ai_name}
          enabled={settings.wake_enabled}
          version={profile.map((p) => p.updated_at).join('|')}
          onChange={(enabled) => setSettings((prev) => (prev ? { ...prev, wake_enabled: enabled } : prev))}
        />

        <details className="advanced">
          <summary>詳しい設定</summary>
        <label className="field">
          <span>会話に使うモデル</span>
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
            返事の自由さ（temperature）: <strong>{settings.temperature.toFixed(1)}</strong>
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
          <span>会話をさかのぼって覚えておく長さ（コンテキスト長）</span>
          <select value={settings.num_ctx} onChange={(e) => update('num_ctx', Number(e.target.value))}>
            <option value={2048}>2048（省メモリ）</option>
            <option value={4096}>4096（標準）</option>
            <option value={8192}>8192（GPUメモリを多く使用）</option>
          </select>
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={settings.think} onChange={(e) => update('think', e.target.checked)} />
          じっくり考えるモード（返事の前によく考える。返事は遅くなります）
        </label>
        <label className="field">
          <span>思い出を探すためのモデル（変更すると索引を作り直します）</span>
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
          <span>1回の返事で思い出すことの最大数（0で思い出さない）</span>
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
            （小さいほど、話題に強く関係する思い出だけを使う）
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
        </details>

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

      <InstallPanel />

      <div className="panel">
        <h2>初回の質問への答え</h2>
        <p className="hint">初回設定で答えてくれた内容です。{settings.ai_name} はこれもあなたを知る手がかりにします。</p>
        {profile.filter((entry) => entry.key.startsWith('setup.')).map((entry) => (
          <ProfileEditor
            key={entry.key}
            entry={entry}
            onSaved={(saved) => setProfile((prev) => prev.map((p) => (p.key === saved.key ? saved : p)))}
          />
        ))}
      </div>

      <div className="panel">
        <h2>ダウンロードしたモデル</h2>
        <p className="hint">会話や思い出探しに使うデータです。すべてこの PC の中で動きます。</p>
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
                  <td>{m.kind === 'embedding' ? '思い出探し' : '会話'}</td>
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
          保存データ（あなたのこと・思い出・会話）は暗号化され、暗号鍵はこのPCのWindowsアカウントで保護されています。
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
