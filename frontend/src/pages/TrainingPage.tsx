import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { ConversationSummary, TrainingEnvironment, TrainingExample, TrainingParams, TrainingRun } from '../api/types'
import { formatDate } from '../lib/labels'

type Tab = 'data' | 'run' | 'results'
type Feedback = { kind: 'ok' | 'error'; text: string } | null

const SOURCE_LABELS = { conversation: '保存した会話', manual: '手動入力', distill: '蒸留（教師モデル）' } as const

function FeedbackText({ feedback }: { feedback: Feedback }) {
  if (!feedback) return null
  return (
    <p className={feedback.kind === 'ok' ? 'ok-text' : 'error-text'} role={feedback.kind === 'error' ? 'alert' : 'status'}>
      {feedback.text}
    </p>
  )
}

export function TrainingPage() {
  const [tab, setTab] = useState<Tab>('data')
  return (
    <section className="page training-page">
      <h1>成長</h1>
      <p className="hint">
        保存した会話から「理想の返答」を選んで学習させ、AIをあなたらしく調整します。学習は必ず手動で実行し、承認したデータだけを使います。
      </p>
      <div className="tabs" role="tablist">
        {(
          [
            ['data', '学習データ'],
            ['run', '学習の実行'],
            ['results', '学習結果'],
          ] as [Tab, string][]
        ).map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={`tab${tab === id ? ' active' : ''}`} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      {tab === 'data' && <DataTab />}
      {tab === 'run' && <RunTab onStarted={() => setTab('results')} />}
      {tab === 'results' && <ResultsTab />}
    </section>
  )
}

// ===================== 学習データ =====================

function DataTab() {
  const [filter, setFilter] = useState<'pending' | 'approved' | 'rejected'>('pending')
  const [data, setData] = useState<{ examples: TrainingExample[]; counts: Record<string, number> } | null>(null)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [selected, setSelected] = useState('')
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setData(await api.trainingExamples(filter))
    } catch (err) {
      setFeedback({ kind: 'error', text: errorMessage(err) })
    }
  }, [filter])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    api.conversations().then(setConversations, () => undefined)
  }, [])

  const run = async (fn: () => Promise<string>) => {
    setBusy(true)
    setFeedback(null)
    try {
      setFeedback({ kind: 'ok', text: await fn() })
      await load()
    } catch (err) {
      setFeedback({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  const exportData = () =>
    run(async () => {
      if (!window.confirm('承認済みの学習データを JSONL ファイルとして保存します。ファイルは暗号化されません。よろしいですか？')) {
        return 'エクスポートを取り消しました。'
      }
      const blob = await api.exportTrainingExamples()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'twin-training-data.jsonl'
      a.click()
      URL.revokeObjectURL(url)
      return 'エクスポートしました。ファイルの取り扱いに注意してください。'
    })

  return (
    <div className="tab-panel">
      <div className="panel">
        <h2>学習データを集める</h2>
        <p className="hint">学習データは「この会話を保存」をオンにした会話からのみ作れます。作成直後は「承認待ち」で、承認したものだけが学習に使われます。</p>
        <div className="toolbar">
          <label className="sr-only" htmlFor="conv-select">
            会話
          </label>
          <select id="conv-select" value={selected} onChange={(e) => setSelected(e.target.value)}>
            <option value="">保存した会話を選択</option>
            {conversations.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}（{c.message_count}件）
              </option>
            ))}
          </select>
          <button
            className="btn"
            disabled={!selected || busy}
            onClick={() => void run(async () => `${(await api.trainingFromConversation(selected)).created} 件の候補を追加しました。`)}
          >
            会話から候補を作る
          </button>
          <button className="btn" onClick={() => setAdding(true)}>
            手動で追加
          </button>
          <button
            className="btn"
            disabled={busy}
            title="承認済みデータの質問に教師モデル（会話用モデル）が答え、その回答を承認待ちに追加します"
            onClick={() => void run(async () => {
              const r = await api.distill(5)
              return `教師モデル（${r.teacher}）の回答を ${r.created} 件、承認待ちに追加しました。`
            })}
          >
            {busy ? '処理中…' : '蒸留データを作る'}
          </button>
        </div>
        {adding && (
          <ExampleForm
            onCancel={() => setAdding(false)}
            onSubmit={(u, a) =>
              void run(async () => {
                await api.addTrainingExample(u, a)
                setAdding(false)
                return '承認待ちに追加しました。'
              })
            }
          />
        )}
        <FeedbackText feedback={feedback} />
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>データ一覧</h2>
          <div className="actions">
            <button className="btn small" onClick={() => void run(async () => `重複を ${(await api.dedupeTrainingExamples()).removed} 件削除しました。`)}>
              重複を削除
            </button>
            <button className="btn small" disabled={!data?.counts.approved} onClick={() => void exportData()}>
              承認済みをエクスポート
            </button>
          </div>
        </div>
        <div className="tabs small-tabs" role="tablist">
          {(['pending', 'approved', 'rejected'] as const).map((s) => (
            <button key={s} role="tab" aria-selected={filter === s} className={`tab${filter === s ? ' active' : ''}`} onClick={() => setFilter(s)}>
              {{ pending: '承認待ち', approved: '承認済み', rejected: '却下' }[s]}（{data?.counts[s] ?? 0}）
            </button>
          ))}
        </div>
        {!data ? (
          <p>読み込み中…</p>
        ) : data.examples.length === 0 ? (
          <p className="empty">データはありません。</p>
        ) : (
          <ul className="memory-list">
            {data.examples.map((ex) => (
              <ExampleItem key={ex.id} example={ex} onChanged={() => void load()} onError={(m) => setFeedback({ kind: 'error', text: m })} />
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function ExampleForm({
  initial,
  onCancel,
  onSubmit,
}: {
  initial?: TrainingExample
  onCancel: () => void
  onSubmit: (user: string, assistant: string) => void
}) {
  const [user, setUser] = useState(initial?.user_text ?? '')
  const [assistant, setAssistant] = useState(initial?.assistant_text ?? '')
  return (
    <div className="panel memory-form">
      <label className="field">
        <span>あなたの発言</span>
        <textarea value={user} rows={2} maxLength={2000} onChange={(e) => setUser(e.target.value)} />
      </label>
      <label className="field">
        <span>理想の返答（AIにこう答えてほしい）</span>
        <textarea value={assistant} rows={4} maxLength={4000} onChange={(e) => setAssistant(e.target.value)} />
      </label>
      <div className="actions">
        <button className="btn" onClick={onCancel}>
          キャンセル
        </button>
        <button className="btn primary" disabled={!user.trim() || !assistant.trim()} onClick={() => onSubmit(user, assistant)}>
          保存
        </button>
      </div>
    </div>
  )
}

function ExampleItem({ example, onChanged, onError }: { example: TrainingExample; onChanged: () => void; onError: (m: string) => void }) {
  const [editing, setEditing] = useState(false)
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn()
      onChanged()
    } catch (err) {
      onError(errorMessage(err))
    }
  }
  if (editing) {
    return (
      <li>
        <ExampleForm
          initial={example}
          onCancel={() => setEditing(false)}
          onSubmit={(user_text, assistant_text) =>
            void act(async () => {
              await api.updateTrainingExample(example.id, { user_text, assistant_text })
              setEditing(false)
            })
          }
        />
      </li>
    )
  }
  return (
    <li className={`memory-item panel${example.status === 'pending' ? ' pending' : ''}`}>
      <div className="memory-head">
        <span className="tag">{SOURCE_LABELS[example.source]}</span>
        <span className="hint">{formatDate(example.updated_at)}</span>
      </div>
      <p className="memory-content">
        <strong>あなた:</strong> {example.user_text}
      </p>
      <p className="memory-content">
        <strong>AI:</strong> {example.assistant_text}
      </p>
      {example.warnings.map((w) => (
        <p key={w} className="warn-text">
          ⚠ {w}
        </p>
      ))}
      <div className="actions">
        <button className="btn small" onClick={() => setEditing(true)}>
          修正
        </button>
        {example.status !== 'approved' && (
          <button className="btn small primary" onClick={() => void act(() => api.decideTrainingExample(example.id, 'approve'))}>
            承認
          </button>
        )}
        {example.status === 'pending' && (
          <button className="btn small" onClick={() => void act(() => api.decideTrainingExample(example.id, 'reject'))}>
            却下
          </button>
        )}
        {example.status !== 'pending' && (
          <button className="btn small" onClick={() => void act(() => api.decideTrainingExample(example.id, 'pending'))}>
            承認待ちに戻す
          </button>
        )}
        <button
          className="btn small danger"
          onClick={() => {
            if (window.confirm('この学習データを削除しますか？')) void act(() => api.deleteTrainingExample(example.id))
          }}
        >
          削除
        </button>
      </div>
    </li>
  )
}

// ===================== 学習の実行 =====================

const DEFAULT_PARAMS: TrainingParams = {
  base: 'qwen3-1.7b',
  epochs: 2,
  learning_rate: 0.0001,
  lora_r: 16,
  lora_alpha: 32,
  max_seq_len: 1024,
  grad_accum: 4,
}

function RunTab({ onStarted }: { onStarted: () => void }) {
  const [env, setEnv] = useState<TrainingEnvironment | null>(null)
  const [params, setParams] = useState<TrainingParams>(DEFAULT_PARAMS)
  const [confirming, setConfirming] = useState(false)
  const [agreed, setAgreed] = useState(false)
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    api.trainingEnvironment().then(setEnv, (err) => setFeedback({ kind: 'error', text: errorMessage(err) }))
  }, [])

  if (!env) return <p>確認中…</p>
  const base = env.bases.find((b) => b.id === params.base)
  const problems = [
    !env.training_python && '学習用の環境（training/.venv）が導入されていません。',
    !env.converter && 'GGUF 変換スクリプト（training/llama.cpp）がありません。',
    base && !base.downloaded && `学習用のモデル（${base.hf_repo}、約${base.size_gb}GB）がダウンロードされていません。`,
    env.approved_examples < env.min_examples && `承認済みの学習データが ${env.min_examples} 件以上必要です（現在 ${env.approved_examples} 件）。`,
    env.running && '別の学習を実行中です。',
  ].filter(Boolean) as string[]
  const set = <K extends keyof TrainingParams>(key: K, value: TrainingParams[K]) => setParams((p) => ({ ...p, [key]: value }))

  const start = async () => {
    setStarting(true)
    setFeedback(null)
    try {
      await api.startTraining(params)
      setConfirming(false)
      onStarted()
    } catch (err) {
      setFeedback({ kind: 'error', text: errorMessage(err) })
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="tab-panel">
      <div className="panel">
        <h2>学習の設定</h2>
        <label className="field">
          <span>ベースモデル</span>
          <select value={params.base} onChange={(e) => set('base', e.target.value)}>
            {env.bases.map((b) => (
              <option key={b.id} value={b.id}>
                {b.label}
                {b.downloaded ? '' : '（未ダウンロード）'}
              </option>
            ))}
          </select>
        </label>
        {base && <p className="hint">{base.note} 学習後は Ollama の「{base.ollama_model}」に学習結果を重ねたモデルとして使います。</p>}
        <div className="form-row">
          <label className="field">
            <span>学習回数（エポック）: {params.epochs}</span>
            <input type="range" min={1} max={10} value={params.epochs} onChange={(e) => set('epochs', Number(e.target.value))} />
          </label>
          <label className="field">
            <span>LoRA ランク: {params.lora_r}</span>
            <select value={params.lora_r} onChange={(e) => set('lora_r', Number(e.target.value))}>
              {[8, 16, 32].map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="field">
          <span>最大の長さ（トークン）: {params.max_seq_len}（短いほどGPUメモリを節約）</span>
          <select value={params.max_seq_len} onChange={(e) => set('max_seq_len', Number(e.target.value))}>
            {[512, 1024, 2048].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        {problems.length > 0 && (
          <div className="banner warn" role="status">
            <ul>
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </div>
        )}
        <div className="actions">
          <button className="btn primary" disabled={problems.length > 0} onClick={() => setConfirming(true)}>
            確認して学習を開始…
          </button>
        </div>
        <FeedbackText feedback={feedback} />
      </div>

      {confirming && base && (
        <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="train-title">
          <div className="dialog panel">
            <h2 id="train-title">学習を開始しますか？</h2>
            <dl className="summary compact">
              <div>
                <dt>ベース</dt>
                <dd>{base.label}</dd>
              </div>
              <div>
                <dt>学習データ</dt>
                <dd>承認済み {env.approved_examples} 件（うち約1割を評価用に使用）</dd>
              </div>
              <div>
                <dt>学習回数</dt>
                <dd>{params.epochs} エポック</dd>
              </div>
            </dl>
            <ul className="hint">
              <li>学習中は GPU を使うため、会話用の AI は一時的に使えません（終了後に自動で再読み込みされます）。</li>
              <li>使用したデータは暗号化して保存し、学習用の一時ファイルは終了後に削除します。</li>
              <li>学習結果は自動では使われません。結果を確認し、「使用する」を押したときだけ切り替わります。いつでも元のモデルに戻せます。</li>
              <li>GPU メモリが不足した場合は失敗として記録されます。</li>
            </ul>
            <label className="checkbox">
              <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
              上記を確認しました
            </label>
            <div className="actions">
              <button className="btn" onClick={() => setConfirming(false)}>
                キャンセル
              </button>
              <button className="btn primary" disabled={!agreed || starting} onClick={() => void start()}>
                {starting ? '開始中…' : '学習を開始する'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ===================== 学習結果 =====================

function ResultsTab() {
  const [data, setData] = useState<{ runs: TrainingRun[]; model: string } | null>(null)
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [logFor, setLogFor] = useState<string | null>(null)
  const [log, setLog] = useState('')

  const load = useCallback(async () => {
    try {
      setData(await api.trainingRuns())
    } catch (err) {
      setFeedback({ kind: 'error', text: errorMessage(err) })
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const running = data?.runs.some((r) => r.status === 'running')
  // 実行中は進捗とログを定期的に更新する
  useEffect(() => {
    if (!running && !logFor) return
    const id = window.setInterval(() => {
      void load()
      if (logFor) api.trainingLog(logFor).then((r) => setLog(r.log), () => undefined)
    }, 3000)
    return () => window.clearInterval(id)
  }, [running, logFor, load])

  const act = async (fn: () => Promise<unknown>, done: string) => {
    setFeedback(null)
    try {
      await fn()
      setFeedback({ kind: 'ok', text: done })
      await load()
    } catch (err) {
      setFeedback({ kind: 'error', text: errorMessage(err) })
    }
  }

  const showLog = async (id: string) => {
    setLogFor(id === logFor ? null : id)
    if (id !== logFor) setLog((await api.trainingLog(id)).log)
  }

  if (!data) return <p>読み込み中…</p>
  const usingTuned = data.model.startsWith('twin-')
  return (
    <div className="tab-panel">
      <div className="panel">
        <p>
          現在の会話モデル: <strong>{data.model}</strong>
          {usingTuned && '（学習済み）'}
        </p>
        {usingTuned && (
          <button className="btn small" onClick={() => void act(() => api.revertTraining(), '元のモデルに戻しました。')}>
            元のモデルに戻す
          </button>
        )}
        <FeedbackText feedback={feedback} />
      </div>
      {data.runs.length === 0 ? (
        <p className="empty">まだ学習していません。</p>
      ) : (
        <ul className="memory-list">
          {data.runs.map((run) => (
            <li key={run.id} className={`memory-item panel${run.active ? ' selected' : ''}`}>
              <div className="memory-head">
                <strong>{run.base}</strong>
                <span className={`tag${run.status === 'failed' ? ' important' : ''}`}>
                  {{ running: '実行中', succeeded: '完了', failed: '失敗', cancelled: '中止' }[run.status]}
                </span>
                {run.active && <span className="tag">使用中</span>}
                <span className="hint">
                  {formatDate(run.created_at)} ・ データ {run.example_count} 件 ・ {run.params.epochs} エポック
                </span>
              </div>
              {run.status === 'running' && run.progress && (
                <div className="progress" aria-live="polite">
                  <div className="progress-bar">
                    <div style={{ width: `${run.progress.total_steps ? Math.round((run.progress.step / run.progress.total_steps) * 100) : 0}%` }} />
                  </div>
                  <span>
                    {run.progress.phase}
                    {run.progress.total_steps > 0 && ` ${run.progress.step}/${run.progress.total_steps}`}
                    {run.progress.loss != null && ` ・ 損失 ${run.progress.loss}`}
                    {run.progress.eta_seconds != null && ` ・ 残り約 ${Math.ceil(run.progress.eta_seconds / 60)} 分`}
                    {run.progress.gpu_memory_gb != null && ` ・ GPU ${run.progress.gpu_memory_gb}GB`}
                  </span>
                </div>
              )}
              {run.error && <p className="error-text">{run.error}</p>}
              {run.metrics && (
                <>
                  <p className="hint">
                    評価用データの損失（小さいほど学習データに近い返答）: 学習前 {run.metrics.eval_loss_before?.toFixed(3) ?? '-'} → 学習後{' '}
                    {run.metrics.eval_loss_after?.toFixed(3) ?? '-'}
                    {run.metrics.train_seconds != null && ` ・ 学習時間 ${Math.ceil(run.metrics.train_seconds / 60)} 分`}
                    {run.metrics.peak_gpu_memory_gb != null && ` ・ 最大GPUメモリ ${run.metrics.peak_gpu_memory_gb}GB`}
                  </p>
                  <details>
                    <summary>学習前後の回答を比べる</summary>
                    {run.metrics.samples.map((s) => (
                      <div key={s.prompt} className="compare">
                        <p>
                          <strong>質問:</strong> {s.prompt}
                        </p>
                        <div className="compare-grid">
                          <div>
                            <span className="hint">学習前</span>
                            <p className="bubble-text">{s.before}</p>
                          </div>
                          <div>
                            <span className="hint">学習後</span>
                            <p className="bubble-text">{s.after}</p>
                          </div>
                        </div>
                      </div>
                    ))}
                  </details>
                </>
              )}
              <div className="actions">
                <button className="btn small" onClick={() => void showLog(run.id)}>
                  {logFor === run.id ? 'ログを閉じる' : 'ログ'}
                </button>
                {run.status === 'running' && (
                  <button className="btn small danger" onClick={() => void act(() => api.cancelTraining(run.id), '学習を中止しました。')}>
                    中止
                  </button>
                )}
                {run.status === 'succeeded' && !run.active && (
                  <button
                    className="btn small primary"
                    onClick={() => void act(() => api.activateTraining(run.id), `会話モデルを「${run.ollama_model}」に切り替えました。`)}
                  >
                    使用する
                  </button>
                )}
                {run.status !== 'running' && (
                  <button
                    className="btn small danger"
                    onClick={() => {
                      if (window.confirm('この学習結果を削除しますか？（使用中の場合は元のモデルに戻ります）')) {
                        void act(() => api.deleteTraining(run.id), '削除しました。')
                      }
                    }}
                  >
                    削除
                  </button>
                )}
              </div>
              {logFor === run.id && <pre className="log-view">{log || '（ログはありません）'}</pre>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
