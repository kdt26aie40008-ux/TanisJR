import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, errorMessage } from '../api/client'
import type { CalendarOperation, ChatMessage, ConversationDetail, UsedMemory } from '../api/types'

export interface DisplayMessage extends ChatMessage {
  id: number
  thinking?: string
  memories?: UsedMemory[]
  /** AI が提案したカレンダー操作（承認されるまで実行されない） */
  proposals?: CalendarOperation[]
}

export interface SendHooks {
  /** 応答の文字が届くたびに呼ばれる（音声会話での逐次読み上げ用） */
  onToken?: (text: string) => void
}

export interface SendResult {
  ok: boolean
  reply: string
  /** エラーで応答が得られなかった（ユーザー発言は取り消し済み） */
  failed: boolean
}

interface ConversationValue {
  messages: DisplayMessage[]
  streaming: boolean
  notice: string
  error: string
  saveEnabled: boolean
  conversationId: string | null
  savingToggle: boolean
  send: (text: string, hooks?: SendHooks) => Promise<SendResult>
  stop: () => void
  clear: () => void
  toggleSave: (enabled: boolean) => Promise<void>
  open: (conversation: ConversationDetail) => void
  setNotice: (message: string) => void
  /** AI から話しかけた言葉を会話に加える（サーバーへは送らない。次の送信から会話の流れとして渡る） */
  say: (text: string) => void
}

const ConversationContext = createContext<ConversationValue | null>(null)

let nextId = 1

const toPayload = (list: DisplayMessage[]): ChatMessage[] =>
  list.filter((m) => m.content).map(({ role, content }) => ({ role, content }))

/**
 * テキストチャットと音声会話で共有する会話の状態。
 * 保存しない会話はこのメモリ上だけに保持する（サーバー・ブラウザーストレージには保存しない）。
 */
export function ConversationProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<DisplayMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [saveDefault, setSaveDefault] = useState(false)
  const [saveEnabled, setSaveEnabled] = useState(false)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [savingToggle, setSavingToggle] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  // 非同期処理の途中でも最新の値を参照するための写し
  const stateRef = useRef({ messages, saveEnabled, conversationId, streaming })
  stateRef.current = { messages, saveEnabled, conversationId, streaming }

  useEffect(() => {
    api.getSettings().then(
      (s) => {
        setSaveDefault(s.save_conversations_default)
        setSaveEnabled((current) => current || s.save_conversations_default)
      },
      () => undefined,
    )
  }, [])

  useEffect(() => () => abortRef.current?.abort(), [])

  const patchMessage = (id: number, patch: (m: DisplayMessage) => DisplayMessage) =>
    setMessages((prev) => prev.map((m) => (m.id === id ? patch(m) : m)))

  const toggleSave = useCallback(async (enabled: boolean) => {
    setError('')
    const { messages: current, conversationId: currentId } = stateRef.current
    if (!enabled) {
      setSaveEnabled(false)
      setConversationId(null)
      if (currentId) setNotice('ここから先の会話は保存されません。保存済みの部分は「思い出 › 会話履歴」から削除できます。')
      return
    }
    setSaveEnabled(true)
    // すでに会話がある場合は、ここまでの内容も含めて保存する
    if (current.some((m) => m.content) && !currentId) {
      setSavingToggle(true)
      try {
        const created = await api.createConversation(toPayload(current))
        setConversationId(created.id)
      } catch (err) {
        setSaveEnabled(false)
        setError(errorMessage(err))
      } finally {
        setSavingToggle(false)
      }
    }
  }, [])

  const send = useCallback(async (text: string, hooks: SendHooks = {}): Promise<SendResult> => {
    const trimmed = text.trim()
    const { messages: current, saveEnabled: save, conversationId: currentId, streaming: busy } = stateRef.current
    if (!trimmed || busy) return { ok: false, reply: '', failed: false }
    const userMsg: DisplayMessage = { id: nextId++, role: 'user', content: trimmed }
    const assistantId = nextId++
    const prior = current.filter((m) => m.content)
    const history = [...prior, userMsg]
    setMessages([...history, { id: assistantId, role: 'assistant', content: '' }])
    setError('')
    setNotice('')
    setStreaming(true)
    stateRef.current.streaming = true

    const controller = new AbortController()
    abortRef.current = controller
    let failed = false
    let reply = ''
    try {
      let targetId = currentId
      if (save && !targetId) {
        targetId = (await api.createConversation(toPayload(prior))).id
        setConversationId(targetId)
      }
      for await (const event of api.chat(toPayload(history), targetId, controller.signal)) {
        if (event.type === 'token') {
          reply += event.content
          patchMessage(assistantId, (m) => ({ ...m, content: m.content + event.content }))
          hooks.onToken?.(event.content)
        } else if (event.type === 'thinking') {
          patchMessage(assistantId, (m) => ({ ...m, thinking: (m.thinking ?? '') + event.content }))
        } else if (event.type === 'memories_used') {
          patchMessage(assistantId, (m) => ({ ...m, memories: event.items }))
        } else if (event.type === 'calendar_proposal') {
          patchMessage(assistantId, (m) => ({ ...m, proposals: [...(m.proposals ?? []), event.operation] }))
        } else if (event.type === 'notice') {
          setNotice(event.message)
        } else if (event.type === 'error') {
          setError(event.message)
          failed = true
        }
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(errorMessage(err))
        failed = true
      }
    } finally {
      setStreaming(false)
      abortRef.current = null
      // 応答が得られなかった場合は空の吹き出しを消す（失敗時はユーザー発言も消し、再送できるようにする）
      if (!reply) {
        setMessages((prev) => prev.filter((m) => m.id !== assistantId && !(failed && m.id === userMsg.id)))
      }
    }
    return { ok: !failed && reply.length > 0, reply, failed: failed && !reply }
  }, [])

  const stop = useCallback(() => abortRef.current?.abort(), [])

  const say = useCallback((text: string) => {
    if (stateRef.current.streaming || !text.trim()) return
    setMessages((prev) => [...prev, { id: nextId++, role: 'assistant', content: text.trim() }])
  }, [])

  const clear = useCallback(() => {
    abortRef.current?.abort()
    setMessages([])
    setConversationId(null)
    setSaveEnabled(saveDefault)
    setNotice('')
    setError('')
  }, [saveDefault])

  const open = useCallback((conversation: ConversationDetail) => {
    abortRef.current?.abort()
    setMessages(conversation.messages.map((m) => ({ id: nextId++, role: m.role, content: m.content })))
    setConversationId(conversation.id)
    setSaveEnabled(true)
    setError('')
    setNotice('')
  }, [])

  const value = useMemo(
    () => ({
      messages,
      streaming,
      notice,
      error,
      saveEnabled,
      conversationId,
      savingToggle,
      send,
      stop,
      clear,
      toggleSave,
      open,
      setNotice,
      say,
    }),
    [messages, streaming, notice, error, saveEnabled, conversationId, savingToggle, send, stop, clear, toggleSave, open, say],
  )
  return <ConversationContext.Provider value={value}>{children}</ConversationContext.Provider>
}

export function useConversation(): ConversationValue {
  const value = useContext(ConversationContext)
  if (!value) throw new Error('ConversationProvider が必要です')
  return value
}
