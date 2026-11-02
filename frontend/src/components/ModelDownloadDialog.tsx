import { useRef, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { CatalogModel, ModelStatus } from '../api/types'

interface Props {
  model: CatalogModel
  status: ModelStatus
  onClose: (downloaded: boolean) => void
}

/** 容量と保存先を提示し、ユーザーが確認した場合のみダウンロードを開始する。 */
export function ModelDownloadDialog({ model, status, onClose }: Props) {
  const [phase, setPhase] = useState<'confirm' | 'pulling' | 'done' | 'error'>('confirm')
  const [progress, setProgress] = useState<{ status: string; ratio: number | null }>({ status: '', ratio: null })
  const [error, setError] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const lowSpace = status.free_space_gb !== null && status.free_space_gb < model.size_gb * 1.2

  const start = async () => {
    const controller = new AbortController()
    abortRef.current = controller
    setPhase('pulling')
    try {
      for await (const event of api.pullModel(model.name, controller.signal)) {
        if (event.type === 'progress') {
          const ratio = event.total ? (event.completed ?? 0) / event.total : null
          setProgress({ status: event.status, ratio })
        } else if (event.type === 'error') {
          setError(event.message)
          setPhase('error')
          return
        } else if (event.type === 'done') {
          setPhase('done')
          return
        }
      }
      setError('ダウンロードが途中で終了しました。もう一度お試しください。')
      setPhase('error')
    } catch (err) {
      if (controller.signal.aborted) {
        setError('ダウンロードを中止しました。')
      } else {
        setError(errorMessage(err))
      }
      setPhase('error')
    }
  }

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="dl-title">
      <div className="dialog panel">
        <h2 id="dl-title">モデルのダウンロード</h2>
        <dl className="summary compact">
          <div>
            <dt>モデル</dt>
            <dd>{model.name}</dd>
          </div>
          <div>
            <dt>容量（目安）</dt>
            <dd>約 {model.size_gb} GB</dd>
          </div>
          <div>
            <dt>保存先（推定）</dt>
            <dd className="path">{status.storage_path}</dd>
          </div>
          <div>
            <dt>空き容量</dt>
            <dd>{status.free_space_gb === null ? '不明' : `${status.free_space_gb} GB`}</dd>
          </div>
        </dl>
        <p className="hint">
          ダウンロードは Ollama が行います。Ollama 側で保存先（OLLAMA_MODELS）を変更している場合は、その場所に保存されます。
        </p>
        {lowSpace && <p className="warn-text">空き容量が不足している可能性があります。</p>}

        {phase === 'pulling' && (
          <div className="progress" aria-live="polite">
            <div className="progress-bar">
              <div style={{ width: `${Math.round((progress.ratio ?? 0) * 100)}%` }} />
            </div>
            <span>
              {progress.status}
              {progress.ratio !== null && ` ${Math.round(progress.ratio * 100)}%`}
            </span>
          </div>
        )}
        {phase === 'done' && <p className="ok-text">ダウンロードが完了しました。</p>}
        {phase === 'error' && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}

        <div className="actions">
          {phase === 'confirm' && (
            <>
              <button className="btn" onClick={() => onClose(false)}>
                キャンセル
              </button>
              <button className="btn primary" onClick={() => void start()}>
                ダウンロードする
              </button>
            </>
          )}
          {phase === 'pulling' && (
            <button className="btn" onClick={() => abortRef.current?.abort()}>
              中止
            </button>
          )}
          {(phase === 'done' || phase === 'error') && (
            <button className="btn primary" onClick={() => onClose(phase === 'done')}>
              閉じる
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
