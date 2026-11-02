import { CATEGORY_LABELS } from '../lib/labels'
import { OperationCard } from './calendar/OperationCard'
import type { DisplayMessage } from '../state/ConversationContext'

interface Props {
  aiName: string
  messages: DisplayMessage[]
  streaming: boolean
  /** 指定すると、AIの発言に読み上げボタンを表示する */
  onSpeak?: (text: string) => void
}

export function MessageList({ aiName, messages, streaming, onSpeak }: Props) {
  return (
    <>
      {messages.map((m) => (
        <div key={m.id} className={`message ${m.role}`}>
          <div className="message-author">{m.role === 'user' ? 'あなた' : aiName}</div>
          {m.thinking && (
            <details className="thinking">
              <summary>思考過程</summary>
              <pre>{m.thinking}</pre>
            </details>
          )}
          <div className="bubble-text">
            {m.content || (streaming && m.role === 'assistant' ? <span className="typing">考えています…</span> : null)}
          </div>
          {m.role === 'assistant' && m.content && onSpeak && (
            <button className="btn small speak-btn" onClick={() => onSpeak(m.content)} aria-label="この発言を読み上げる">
              ▶ 読み上げ
            </button>
          )}
          {m.proposals?.map((op) => <OperationCard key={op.id} operation={op} />)}
          {m.memories && m.memories.length > 0 && (
            <details className="used-memories">
              <summary>参照した記憶（{m.memories.length}）</summary>
              <ul>
                {m.memories.map((mem) => (
                  <li key={mem.id}>
                    <span className="tag">{CATEGORY_LABELS[mem.category] ?? mem.category}</span>
                    {mem.content}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      ))}
    </>
  )
}
