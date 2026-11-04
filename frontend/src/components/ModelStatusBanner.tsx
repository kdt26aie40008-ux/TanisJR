import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { ModelStatus } from '../api/types'
import { ModelDownloadDialog } from './ModelDownloadDialog'

interface Props {
  /** chat: 会話用モデル / embedding: 記憶検索用モデル */
  kind?: 'chat' | 'embedding'
}

/** Ollama 未起動・モデル未導入のときに案内を表示する。問題がなければ何も表示しない。 */
export function ModelStatusBanner({ kind = 'chat' }: Props) {
  const [status, setStatus] = useState<ModelStatus | null>(null)
  const [error, setError] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.modelStatus())
      setError('')
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  if (error) {
    return (
      <div className="banner error" role="alert">
        {error}
      </div>
    )
  }
  if (!status) return null
  if (!status.ollama_available) {
    return (
      <div className="banner error" role="alert">
        {status.message}
        <button className="btn small" onClick={() => void refresh()}>
          再確認
        </button>
      </div>
    )
  }
  const model = kind === 'chat' ? status.configured_model : status.embedding_model
  const installed = kind === 'chat' ? status.configured_model_installed : status.embedding_model_installed
  if (installed) return null

  const catalogEntry = status.catalog.find((m) => m.name === model)
  return (
    <div className="banner warn" role="status">
      {kind === 'chat'
        ? `会話に使うモデル「${model}」がまだ入っていません。`
        : `思い出を探すためのモデル「${model}」がまだ入っていないため、思い出は会話に使われません。`}
      {catalogEntry ? (
        <button className="btn small" onClick={() => setDialogOpen(true)}>
          ダウンロード（約{catalogEntry.size_gb}GB）
        </button>
      ) : (
        <span>設定画面で別のモデルを選択してください。</span>
      )}
      {dialogOpen && catalogEntry && (
        <ModelDownloadDialog
          model={catalogEntry}
          status={status}
          onClose={(downloaded) => {
            setDialogOpen(false)
            void refresh()
            // 記憶検索用モデルを導入したら、保存済みの記憶を索引に追加する
            if (downloaded && kind === 'embedding') void api.reindexMemories().catch(() => undefined)
          }}
        />
      )}
    </div>
  )
}
