import { useEffect, useRef, useState } from 'react'
import { ModelStatusBanner } from '../components/ModelStatusBanner'
import { SaveToggle } from '../components/SaveToggle'
import { MessageList } from '../components/MessageList'
import { useConversation } from '../state/ConversationContext'

const MAX_INPUT = 8000

export function ChatPage({ aiName }: { aiName: string }) {
  const { messages, streaming, notice, error, send, stop, clear } = useConversation()
  const [input, setInput] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: 'end' })
  }, [messages])

  const submit = async () => {
    const text = input.trim()
    if (!text || streaming) return
    setInput('')
    const result = await send(text)
    // 失敗したら入力を戻して再送できるようにする
    if (result.failed) setInput((current) => current || text)
  }

  return (
    <section className="page chat-page">
      <header className="page-header">
        <h1>{aiName}</h1>
        <div className="header-actions">
          <SaveToggle />
          <button className="btn small" onClick={clear} disabled={streaming || messages.length === 0}>
            新しい会話
          </button>
        </div>
      </header>
      <ModelStatusBanner />
      {notice && (
        <div className="banner warn" role="status">
          {notice}
        </div>
      )}

      <div className="messages" aria-live="polite">
        {messages.length === 0 && (
          <p className="empty">
            {aiName} に話しかけてみましょう。意見が違うときは、{aiName} は遠慮なく反論します。
            <br />
            <span className="hint">
              「この会話を保存」をオンにすると、会話が保存され、あなたについての記憶が少しずつ蓄積されます。
            </span>
          </p>
        )}
        <MessageList aiName={aiName} messages={messages} streaming={streaming} />
        <div ref={endRef} />
      </div>

      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}

      <form
        className="composer chat-composer"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <label className="sr-only" htmlFor="chat-input">
          メッセージ
        </label>
        <textarea
          id="chat-input"
          value={input}
          rows={2}
          maxLength={MAX_INPUT}
          placeholder="メッセージを入力（Enterで送信 / Shift+Enterで改行）"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            // 日本語入力の変換確定の Enter では送信しない
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              void submit()
            }
          }}
        />
        {streaming ? (
          <button type="button" className="btn" onClick={stop}>
            停止
          </button>
        ) : (
          <button type="submit" className="btn primary" disabled={!input.trim()}>
            送信
          </button>
        )}
      </form>
    </section>
  )
}
