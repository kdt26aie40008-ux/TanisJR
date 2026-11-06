import { lazy, Suspense } from 'react'
import { CATEGORY_LABELS } from '../lib/labels'

// 数式・書式の表示（KaTeX など約450KB）は、最初の返事を表示するときに読み込む
const MarkdownText = lazy(() => import('./MarkdownText').then((m) => ({ default: m.MarkdownText })))
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
              <summary>考えたこと</summary>
              <pre>{m.thinking}</pre>
            </details>
          )}
          {m.role === 'assistant' && m.content ? (
            // AI の返事は、太字・箇条書き・数式などを整えて表示する
            <div className="bubble-text md-bubble">
              <Suspense fallback={<div className="md">{m.content}</div>}>
                <MarkdownText text={m.content} />
              </Suspense>
            </div>
          ) : (
            <div className="bubble-text">
              {m.content || (streaming && m.role === 'assistant' ? <span className="typing">考えています…</span> : null)}
            </div>
          )}
          {m.role === 'assistant' && m.content && onSpeak && (
            <button className="btn small speak-btn" onClick={() => onSpeak(m.content)} aria-label="この発言を読み上げる">
              もう一度聞く
            </button>
          )}
          {m.proposals?.map((op) => <OperationCard key={op.id} operation={op} />)}
          {m.memories && m.memories.length > 0 && (
            <details className="used-memories">
              <summary>思い出したこと（{m.memories.length}）</summary>
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
