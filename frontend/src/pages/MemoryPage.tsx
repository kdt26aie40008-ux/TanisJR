import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { ConversationDetail, ConversationSummary, Memory, MemoryCategory, MemoryStats } from '../api/types'
import { ModelStatusBanner } from '../components/ModelStatusBanner'
import { CATEGORIES, CATEGORY_LABELS, formatDate } from '../lib/labels'

type Tab = 'memories' | 'pending' | 'history'

interface Props {
  onChanged: () => void
  onOpenConversation: (conversation: ConversationDetail) => void
}

export function MemoryPage({ onChanged, onOpenConversation }: Props) {
  const [tab, setTab] = useState<Tab>('memories')
  const [stats, setStats] = useState<MemoryStats | null>(null)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  const refreshStats = useCallback(() => {
    api.memoryStats().then(setStats, (err) => setMessage({ kind: 'error', text: errorMessage(err) }))
    onChanged()
  }, [onChanged])

  useEffect(() => {
    refreshStats()
  }, [refreshStats])

  const reindex = async () => {
    try {
      const r = await api.reindexMemories()
      setMessage({ kind: 'ok', text: `索引を更新しました（追加 ${r.indexed} 件 / 不要分の削除 ${r.removed_orphans} 件）。` })
      refreshStats()
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  return (
    <section className="page memory-page">
      <h1>思い出</h1>
      <ModelStatusBanner kind="embedding" />
      {stats && stats.unindexed > 0 && stats.embedding_available && (
        <div className="banner warn" role="status">
          検索の索引に入っていない思い出が {stats.unindexed} 件あります。
          <button className="btn small" onClick={() => void reindex()}>
            索引を更新
          </button>
        </div>
      )}
      {message && (
        <p className={message.kind === 'ok' ? 'ok-text' : 'error-text'} role={message.kind === 'error' ? 'alert' : 'status'}>
          {message.text}
        </p>
      )}

      <div className="tabs" role="tablist">
        {(
          [
            ['memories', `思い出${stats ? `（${stats.active}）` : ''}`],
            ['pending', `承認待ち${stats ? `（${stats.pending}）` : ''}`],
            ['history', '会話履歴'],
          ] as [Tab, string][]
        ).map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            className={`tab${tab === id ? ' active' : ''}${id === 'pending' && stats?.pending ? ' attention' : ''}`}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'memories' && <MemoryList onChanged={refreshStats} onOpenConversation={onOpenConversation} />}
      {tab === 'pending' && <PendingList onChanged={refreshStats} />}
      {tab === 'history' && <HistoryList onChanged={refreshStats} onOpenConversation={onOpenConversation} />}
    </section>
  )
}

// ===================== 記憶一覧 =====================

function MemoryList({ onChanged, onOpenConversation }: { onChanged: () => void; onOpenConversation: Props['onOpenConversation'] }) {
  const [items, setItems] = useState<Memory[] | null>(null)
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [error, setError] = useState('')
  const [adding, setAdding] = useState(false)

  const load = useCallback(async (q: string, c: string) => {
    try {
      setItems(await api.memories({ status: 'active', q, category: c }))
      setError('')
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    void load('', '')
  }, [load])

  const reload = () => {
    void load(query, category)
    onChanged()
  }

  return (
    <div className="tab-panel">
      <form
        className="toolbar"
        onSubmit={(e) => {
          e.preventDefault()
          void load(query, category)
        }}
      >
        <label className="sr-only" htmlFor="memory-search">
          思い出を検索
        </label>
        <input id="memory-search" type="search" placeholder="キーワードで検索" value={query} onChange={(e) => setQuery(e.target.value)} />
        <label className="sr-only" htmlFor="memory-category">
          カテゴリ
        </label>
        <select
          id="memory-category"
          value={category}
          onChange={(e) => {
            setCategory(e.target.value)
            void load(query, e.target.value)
          }}
        >
          <option value="">すべてのカテゴリ</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {CATEGORY_LABELS[c]}
            </option>
          ))}
        </select>
        <button type="submit" className="btn">
          検索
        </button>
        <button type="button" className="btn primary" onClick={() => setAdding(true)}>
          思い出を追加
        </button>
      </form>
      {adding && (
        <MemoryForm
          onCancel={() => setAdding(false)}
          onSaved={() => {
            setAdding(false)
            reload()
          }}
        />
      )}
      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}
      {items === null ? (
        <p>読み込み中…</p>
      ) : items.length === 0 ? (
        <p className="empty">
          {query || category ? '条件に合う思い出はありません。' : 'まだ思い出はありません。保存した会話から少しずつ増えていきます。'}
        </p>
      ) : (
        <ul className="memory-list">
          {items.map((m) => (
            <MemoryItem key={m.id} memory={m} onChanged={reload} onOpenConversation={onOpenConversation} />
          ))}
        </ul>
      )}
    </div>
  )
}

function MemoryForm({ onCancel, onSaved }: { onCancel: () => void; onSaved: () => void }) {
  const [content, setContent] = useState('')
  const [category, setCategory] = useState<MemoryCategory>('preference')
  const [importance, setImportance] = useState(5)
  const [error, setError] = useState('')

  const save = async () => {
    try {
      await api.createMemory({ content, category, importance })
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="panel memory-form">
      <label className="field">
        <span>内容（例: ユーザーは辛い食べ物が苦手）</span>
        <textarea value={content} maxLength={500} rows={2} onChange={(e) => setContent(e.target.value)} />
      </label>
      <div className="form-row">
        <CategorySelect value={category} onChange={setCategory} />
        <ImportanceInput value={importance} onChange={setImportance} />
      </div>
      {error && <p className="error-text">{error}</p>}
      <div className="actions">
        <button className="btn" onClick={onCancel}>
          キャンセル
        </button>
        <button className="btn primary" disabled={!content.trim()} onClick={() => void save()}>
          保存
        </button>
      </div>
    </div>
  )
}

function CategorySelect({ value, onChange }: { value: MemoryCategory; onChange: (v: MemoryCategory) => void }) {
  return (
    <label className="field">
      <span>カテゴリ</span>
      <select value={value} onChange={(e) => onChange(e.target.value as MemoryCategory)}>
        {CATEGORIES.map((c) => (
          <option key={c} value={c}>
            {CATEGORY_LABELS[c]}
          </option>
        ))}
      </select>
    </label>
  )
}

function ImportanceInput({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <label className="field">
      <span>重要度: {value}</span>
      <input type="range" min={1} max={10} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  )
}

function sourceLabel(m: Memory): string {
  if (m.source_type === 'user_manual') return 'あなたが手動で追加'
  if (m.source_conversation_title) return `会話「${m.source_conversation_title}」`
  return '会話（削除済み）'
}

function statusLabel(m: Memory): string {
  return { auto: '自動保存', confirmed: '確認済み', pending: '承認待ち' }[m.confirmation_status]
}

function MemoryItem({
  memory,
  onChanged,
  onOpenConversation,
}: {
  memory: Memory
  onChanged: () => void
  onOpenConversation: Props['onOpenConversation']
}) {
  const [editing, setEditing] = useState(false)
  const [content, setContent] = useState(memory.content)
  const [category, setCategory] = useState(memory.category)
  const [importance, setImportance] = useState(memory.importance)
  const [error, setError] = useState('')

  const save = async () => {
    try {
      await api.updateMemory(memory.id, { content, category, importance })
      setEditing(false)
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const remove = async () => {
    if (!window.confirm(`この思い出を削除しますか？\n\n${memory.content}`)) return
    try {
      await api.deleteMemory(memory.id)
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const openSource = async () => {
    if (!memory.source_conversation_id) return
    try {
      onOpenConversation(await api.conversation(memory.source_conversation_id))
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <li className="memory-item panel">
      {editing ? (
        <>
          <label className="field">
            <span>内容</span>
            <textarea value={content} maxLength={500} rows={2} onChange={(e) => setContent(e.target.value)} />
          </label>
          <div className="form-row">
            <CategorySelect value={category} onChange={setCategory} />
            <ImportanceInput value={importance} onChange={setImportance} />
          </div>
          <div className="actions">
            <button className="btn" onClick={() => setEditing(false)}>
              キャンセル
            </button>
            <button className="btn primary" disabled={!content.trim()} onClick={() => void save()}>
              保存
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="memory-head">
            <span className={`tag${memory.sensitivity === 'important' ? ' important' : ''}`}>
              {CATEGORY_LABELS[memory.category] ?? memory.category}
            </span>
            <span className="hint">
              重要度 {memory.importance} ・ {statusLabel(memory)}
              {!memory.indexed && ' ・ 索引未登録'}
            </span>
          </div>
          <p className="memory-content">{memory.content}</p>
          <details className="memory-source">
            <summary>出典: {sourceLabel(memory)}</summary>
            <dl className="summary compact">
              {memory.source_excerpt && (
                <div>
                  <dt>元の発言</dt>
                  <dd>{memory.source_excerpt}</dd>
                </div>
              )}
              <div>
                <dt>作成</dt>
                <dd>{formatDate(memory.created_at)}</dd>
              </div>
              <div>
                <dt>更新</dt>
                <dd>{formatDate(memory.updated_at)}</dd>
              </div>
            </dl>
            {memory.source_conversation_title && (
              <button className="btn small" onClick={() => void openSource()}>
                会話を開く
              </button>
            )}
          </details>
          <div className="actions">
            <button className="btn small" onClick={() => setEditing(true)}>
              修正
            </button>
            <button className="btn small danger" onClick={() => void remove()}>
              削除
            </button>
          </div>
        </>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </li>
  )
}

// ===================== 承認待ち =====================

function PendingList({ onChanged }: { onChanged: () => void }) {
  const [items, setItems] = useState<Memory[] | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setItems(await api.memories({ status: 'pending' }))
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const done = () => {
    void load()
    onChanged()
  }

  return (
    <div className="tab-panel">
      <p className="hint">
        個人情報・性格・価値観など、あなたへの影響が大きい情報は、承認するまで保存・利用されません。拒否した情報は削除されます。
      </p>
      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}
      {items === null ? (
        <p>読み込み中…</p>
      ) : items.length === 0 ? (
        <p className="empty">承認待ちの情報はありません。</p>
      ) : (
        <ul className="memory-list">
          {items.map((m) => (
            <PendingItem key={m.id} memory={m} onDone={done} />
          ))}
        </ul>
      )}
    </div>
  )
}

function PendingItem({ memory, onDone }: { memory: Memory; onDone: () => void }) {
  const [content, setContent] = useState(memory.content)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await fn()
      onDone()
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <li className="memory-item panel pending">
      <div className="memory-head">
        <span className="tag important">{CATEGORY_LABELS[memory.category] ?? memory.category}</span>
        <span className="hint">重要度 {memory.importance}</span>
      </div>
      <label className="field">
        <span>保存する内容（必要なら修正してから承認できます）</span>
        <textarea value={content} maxLength={500} rows={2} onChange={(e) => setContent(e.target.value)} />
      </label>
      {memory.source_excerpt && (
        <p className="hint">
          元の発言: 「{memory.source_excerpt}」{memory.source_conversation_title && `（会話「${memory.source_conversation_title}」）`}
        </p>
      )}
      <div className="actions">
        <button className="btn danger" disabled={busy} onClick={() => void act(() => api.rejectMemory(memory.id))}>
          拒否（削除）
        </button>
        <button
          className="btn primary"
          disabled={busy || !content.trim()}
          onClick={() =>
            void act(() => api.approveMemory(memory.id, content.trim() !== memory.content ? { content } : undefined))
          }
        >
          承認して保存
        </button>
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </li>
  )
}

// ===================== 会話履歴 =====================

function HistoryList({ onChanged, onOpenConversation }: { onChanged: () => void; onOpenConversation: Props['onOpenConversation'] }) {
  const [items, setItems] = useState<ConversationSummary[] | null>(null)
  const [error, setError] = useState('')
  const [deleting, setDeleting] = useState<ConversationSummary | null>(null)
  const [alsoMemories, setAlsoMemories] = useState(false)

  const load = useCallback(async () => {
    try {
      setItems(await api.conversations())
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const open = async (id: string) => {
    try {
      onOpenConversation(await api.conversation(id))
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const confirmDelete = async () => {
    if (!deleting) return
    try {
      await api.deleteConversation(deleting.id, alsoMemories)
      setDeleting(null)
      void load()
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="tab-panel">
      <p className="hint">「この会話を保存」をオンにした会話だけが表示されます。</p>
      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}
      {items === null ? (
        <p>読み込み中…</p>
      ) : items.length === 0 ? (
        <p className="empty">保存された会話はありません。</p>
      ) : (
        <ul className="memory-list">
          {items.map((c) => (
            <li key={c.id} className="memory-item panel conversation-item">
              <div>
                <p className="memory-content">{c.title}</p>
                <span className="hint">
                  {formatDate(c.updated_at)} ・ {c.message_count}件のメッセージ
                </span>
              </div>
              <div className="actions">
                <button className="btn small" onClick={() => void open(c.id)}>
                  開く
                </button>
                <button
                  className="btn small danger"
                  onClick={() => {
                    setAlsoMemories(false)
                    setDeleting(c)
                  }}
                >
                  削除
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {deleting && (
        <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="del-title">
          <div className="dialog panel">
            <h2 id="del-title">会話を削除</h2>
            <p>「{deleting.title}」を削除します。元に戻せません。</p>
            <label className="checkbox">
              <input type="checkbox" checked={alsoMemories} onChange={(e) => setAlsoMemories(e.target.checked)} />
              この会話から覚えた思い出も削除する
            </label>
            {!alsoMemories && <p className="hint">思い出は残り、出典は「会話（削除済み）」になります。</p>}
            <div className="actions">
              <button className="btn" onClick={() => setDeleting(null)}>
                キャンセル
              </button>
              <button className="btn danger" onClick={() => void confirmDelete()}>
                削除する
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
