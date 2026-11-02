import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from './api/client'
import { useHashRoute } from './lib/useHashRoute'
import { ROUTES } from './routes'
import { AvatarPage } from './pages/AvatarPage'
import { CalendarPage } from './pages/CalendarPage'
import { TrainingPage } from './pages/TrainingPage'
import { ChatPage } from './pages/ChatPage'
import { ComingSoonPage } from './pages/ComingSoonPage'
import { MemoryPage } from './pages/MemoryPage'
import { RestorePage } from './pages/RestorePage'
import { SettingsPage } from './pages/SettingsPage'
import { SetupPage } from './pages/SetupPage'
import { VoicePage } from './pages/VoicePage'
import { ConversationProvider, useConversation } from './state/ConversationContext'

type Boot =
  | { state: 'loading' }
  | { state: 'error'; message: string }
  | { state: 'locked'; reason: string }
  | { state: 'ready'; setupDone: boolean; aiName: string }

export function App() {
  const [boot, setBoot] = useState<Boot>({ state: 'loading' })
  const [, navigate] = useHashRoute()

  const load = useCallback(async () => {
    setBoot({ state: 'loading' })
    try {
      const health = await api.health()
      if (health.data_locked) {
        setBoot({ state: 'locked', reason: health.locked_reason ?? 'データがロックされています。' })
        return
      }
      const [status, settings] = await Promise.all([api.setupStatus(), api.getSettings()])
      setBoot({ state: 'ready', setupDone: status.completed, aiName: settings.ai_name })
    } catch (err) {
      setBoot({ state: 'error', message: errorMessage(err) })
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  if (boot.state === 'loading') {
    return <div className="center-screen">読み込み中…</div>
  }
  if (boot.state === 'error') {
    return (
      <div className="center-screen">
        <div className="panel error-panel" role="alert">
          <p>{boot.message}</p>
          <button className="btn" onClick={() => void load()}>
            再試行
          </button>
        </div>
      </div>
    )
  }
  if (boot.state === 'locked') {
    return <RestorePage reason={boot.reason} onRestored={() => void load()} />
  }
  if (!boot.setupDone) {
    return (
      <SetupPage
        onComplete={(aiName) => {
          setBoot({ state: 'ready', setupDone: true, aiName })
          navigate('chat')
        }}
      />
    )
  }
  return (
    <ConversationProvider>
      <MainLayout
        aiName={boot.aiName}
        onAiNameChange={(aiName) => setBoot({ ...boot, aiName })}
        onRestored={() => void load()}
      />
    </ConversationProvider>
  )
}

interface LayoutProps {
  aiName: string
  onAiNameChange: (name: string) => void
  onRestored: () => void
}

function MainLayout({ aiName, onAiNameChange, onRestored }: LayoutProps) {
  const [route, navigate] = useHashRoute()
  const [pendingCount, setPendingCount] = useState(0)
  const { open } = useConversation()

  const refreshPending = useCallback(() => {
    api.memoryStats().then(
      (s) => setPendingCount(s.pending),
      () => undefined,
    )
  }, [])

  // 画面を切り替えるたびに承認待ちの件数を更新する
  useEffect(() => {
    refreshPending()
  }, [route, refreshPending])

  const active = ROUTES.find((r) => r.id === route) ?? ROUTES[0]
  return (
    <div className="layout">
      <nav className="sidebar" aria-label="メインメニュー">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            ◆
          </span>
          <span className="brand-name">{aiName}</span>
        </div>
        <ul>
          {ROUTES.map((r) => (
            <li key={r.id}>
              <a
                href={`#/${r.id}`}
                className={`nav-link${r.id === active.id ? ' active' : ''}${r.plannedPhase ? ' planned' : ''}`}
                aria-current={r.id === active.id ? 'page' : undefined}
              >
                {r.label}
                {r.plannedPhase && <span className="badge">準備中</span>}
                {r.id === 'memory' && pendingCount > 0 && (
                  <span className="badge attention" aria-label={`承認待ち ${pendingCount}件`}>
                    {pendingCount}
                  </span>
                )}
              </a>
            </li>
          ))}
        </ul>
      </nav>
      <main className="content">
        {/* チャットは常にマウントしておき、画面を切り替えても入力中の内容を保つ */}
        <div hidden={active.id !== 'chat'}>
          <ChatPage aiName={aiName} />
        </div>
        {active.plannedPhase && <ComingSoonPage route={active} />}
        {active.id === 'voice' && <VoicePage aiName={aiName} />}
        {active.id === 'avatar' && <AvatarPage />}
        {active.id === 'calendar' && <CalendarPage />}
        {active.id === 'training' && <TrainingPage />}
        {active.id === 'memory' && (
          <MemoryPage
            onChanged={refreshPending}
            onOpenConversation={(conversation) => {
              open(conversation)
              navigate('chat')
            }}
          />
        )}
        {active.id === 'settings' && <SettingsPage onAiNameChange={onAiNameChange} onRestored={onRestored} />}
      </main>
    </div>
  )
}
