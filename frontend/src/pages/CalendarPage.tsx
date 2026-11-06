import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { AppSettings, CalendarEvent, CalendarOperation, CalendarStatus, EventDraft, SystemStatus } from '../api/types'
import { OperationCard } from '../components/calendar/OperationCard'
import { dayKey, formatDay, formatRange, toLocalInput } from '../lib/datetime'

const NOTIFY_OPTIONS: [string, string][] = [
  ['', '既定'],
  ['-1', '通知しない'],
  ['0', '開始時刻'],
  ['5', '5分前'],
  ['10', '10分前'],
  ['15', '15分前'],
  ['30', '30分前'],
  ['60', '1時間前'],
  ['1440', '1日前'],
]

export function CalendarPage() {
  const [status, setStatus] = useState<CalendarStatus | null>(null)
  const [error, setError] = useState('')
  const [events, setEvents] = useState<CalendarEvent[] | null>(null)
  const [pending, setPending] = useState<CalendarOperation[]>([])
  const [editing, setEditing] = useState<CalendarEvent | 'new' | null>(null)
  const [newDay, setNewDay] = useState<string | null>(null)
  // 月の表示を読み直すための合図
  const [version, setVersion] = useState(0)

  const local = status?.backend !== 'google'
  const usable = Boolean(status && (local || status.connected))

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await api.calendarStatus())
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  const loadData = useCallback(async () => {
    try {
      const [ev, ops] = await Promise.all([api.calendarEvents(14), api.calendarOperations('pending')])
      setEvents(ev)
      setPending(ops)
      setVersion((v) => v + 1)
      setError('')
    } catch (err) {
      setError(errorMessage(err))
      void loadStatus()
    }
  }, [loadStatus])

  useEffect(() => {
    void loadStatus()
  }, [loadStatus])

  useEffect(() => {
    if (usable) void loadData()
  }, [usable, status?.backend, loadData])

  const propose = async (value: Parameters<typeof api.proposeCalendarOperation>[0]) => {
    try {
      const op = await api.proposeCalendarOperation(value)
      setEditing(null)
      if (op.status === 'pending') {
        // Google カレンダーでは、承認するまで反映しない
        setPending((prev) => [op, ...prev])
        document.getElementById('pending-operations')?.scrollIntoView?.({ behavior: 'smooth' })
      } else {
        // アプリ内カレンダーでは、本人の操作はすぐ反映される
        await loadData()
      }
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const switchBackend = async (backend: 'local' | 'google') => {
    try {
      await api.updateSettings({ calendar_backend: backend })
      setEvents(null)
      await loadStatus()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const openNew = (day: string | null) => {
    setNewDay(day)
    setEditing('new')
  }

  const form = editing && (
    <EventForm
      key={editing === 'new' ? `new-${newDay}` : editing.id}
      initial={editing === 'new' ? null : editing}
      day={editing === 'new' ? newDay : null}
      local={local}
      onCancel={() => setEditing(null)}
      onSubmit={(draft) =>
        void propose(editing === 'new' ? { action: 'create', draft } : { action: 'update', event_id: editing.id, draft })
      }
    />
  )

  return (
    <section className="page calendar-page">
      <h1>予定</h1>
      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}

      {status && !local && (
        <ConnectionPanel status={status} onChanged={setStatus} onError={setError} reload={loadStatus} />
      )}

      {status && local && (
        <MonthCalendar
          version={version}
          onAdd={(day) => openNew(day)}
          onEdit={setEditing}
          onDelete={(e) => {
            if (window.confirm(`「${e.summary}」を削除しますか？`)) void propose({ action: 'delete', event_id: e.id })
          }}
          onError={setError}
          form={form}
        />
      )}

      {usable && (
        <>
          {(!local || pending.length > 0) && (
          <div className="panel" id="pending-operations">
            <h2>承認待ちの操作</h2>
            {local && (
              <p className="hint">会話の中で提案された予定です。承認したときだけカレンダーに追加・変更されます。</p>
            )}
            {pending.length === 0 ? (
              <p className="hint">承認待ちの操作はありません。予定の追加・変更・削除は、ここで承認したときだけ実行されます。</p>
            ) : (
              pending.map((op) => (
                <OperationCard
                  key={op.id}
                  operation={op}
                  onChanged={(next) => {
                    if (next.status !== 'pending') {
                      window.setTimeout(() => void loadData(), 1500)
                    }
                  }}
                />
              ))
            )}
          </div>
          )}

          <div className="panel">
            <div className="panel-head">
              <h2>これからの予定（14日間）</h2>
              <div className="actions">
                <button className="btn small" onClick={() => void loadData()}>
                  更新
                </button>
                <button className="btn small primary" onClick={() => openNew(null)}>
                  予定を追加
                </button>
              </div>
            </div>
            {!local && form}
            {events === null ? (
              <p>読み込み中…</p>
            ) : events.length === 0 ? (
              <p className="empty">予定はありません。</p>
            ) : (
              <EventList
                events={events}
                onEdit={setEditing}
                onDelete={(e) => {
                  if (!local || window.confirm(`「${e.summary}」を削除しますか？`)) void propose({ action: 'delete', event_id: e.id })
                }}
                onError={setError}
              />
            )}
          </div>
        </>
      )}

      <NotificationPanel />

      {status && (
        <div className="panel">
          <details className="advanced google-switch">
            <summary>Google カレンダーと連携する（詳しい設定）</summary>
            {local ? (
              <>
                <p className="hint">
                  いまはアプリ内のカレンダーを使っています。予定はこの PC の、あなたの Windows ユーザーのデータにだけ暗号化して保存され、
                  ほかの人と共有されることはありません。Google カレンダーとの連携は、正式公開のときに使えるようにする予定です（準備中）。
                </p>
                <div className="actions wrap">
                  <button className="btn small" onClick={() => void switchBackend('google')}>
                    Google カレンダーに切り替える
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="hint">いまは Google カレンダーを使っています。アプリ内の予定は消えずに残っています。</p>
                <div className="actions wrap">
                  <button className="btn small" onClick={() => void switchBackend('local')}>
                    アプリ内のカレンダーに戻す
                  </button>
                </div>
              </>
            )}
          </details>
        </div>
      )}
      <ServicePanel />
    </section>
  )
}

// ===================== 月の表示（アプリ内カレンダー） =====================

const WEEK_LABELS = ['日', '月', '火', '水', '木', '金', '土']

function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** 月のマス目（日曜始まり・6週）。予定のある日を一覧で見て、日付を押すとその日の予定と追加ができる */
function MonthCalendar({
  version,
  onAdd,
  onEdit,
  onDelete,
  onError,
  form,
}: {
  version: number
  onAdd: (day: string) => void
  onEdit: (e: CalendarEvent) => void
  onDelete: (e: CalendarEvent) => void
  onError: (m: string) => void
  form: React.ReactNode
}) {
  const today = isoDay(new Date())
  const [month, setMonth] = useState(() => {
    const d = new Date()
    return new Date(d.getFullYear(), d.getMonth(), 1)
  })
  const [selected, setSelected] = useState(today)
  const [events, setEvents] = useState<CalendarEvent[]>([])

  const gridStart = new Date(month)
  gridStart.setDate(1 - month.getDay())
  const days = Array.from({ length: 42 }, (_, i) => {
    const d = new Date(gridStart)
    d.setDate(gridStart.getDate() + i)
    return d
  })
  const startKey = isoDay(gridStart)

  useEffect(() => {
    api.calendarEvents(42, startKey).then(setEvents, (err) => onError(errorMessage(err)))
  }, [startKey, version, onError])

  // 複数日にまたがる予定は、またがるすべての日に表示する
  const byDay = new Map<string, CalendarEvent[]>()
  for (const e of events) {
    const first = dayKey(e.start)
    const last = e.all_day ? e.end : dayKey(new Date(new Date(e.end).getTime() - 1).toISOString())
    for (const d of days) {
      const key = isoDay(d)
      if (key >= first && key <= last) byDay.set(key, [...(byDay.get(key) ?? []), e])
    }
  }
  const selectedEvents = byDay.get(selected) ?? []
  const move = (delta: number) => setMonth(new Date(month.getFullYear(), month.getMonth() + delta, 1))

  return (
    <div className="panel month-panel">
      <div className="panel-head">
        <h2>
          {month.getFullYear()}年{month.getMonth() + 1}月
        </h2>
        <div className="actions">
          <button className="btn small" onClick={() => move(-1)} aria-label="前の月">
            ‹
          </button>
          <button
            className="btn small"
            onClick={() => {
              setMonth(new Date(new Date().getFullYear(), new Date().getMonth(), 1))
              setSelected(today)
            }}
          >
            今日
          </button>
          <button className="btn small" onClick={() => move(1)} aria-label="次の月">
            ›
          </button>
        </div>
      </div>
      <div className="month-grid" role="grid" aria-label="月のカレンダー">
        {WEEK_LABELS.map((w, i) => (
          <div key={w} className={`month-week${i === 0 ? ' sun' : i === 6 ? ' sat' : ''}`} role="columnheader">
            {w}
          </div>
        ))}
        {days.map((d) => {
          const key = isoDay(d)
          const items = byDay.get(key) ?? []
          const outside = d.getMonth() !== month.getMonth()
          return (
            <button
              key={key}
              type="button"
              role="gridcell"
              className={`month-day${outside ? ' outside' : ''}${key === today ? ' today' : ''}${key === selected ? ' selected' : ''}`}
              onClick={() => setSelected(key)}
              aria-label={`${d.getMonth() + 1}月${d.getDate()}日${items.length ? `、予定${items.length}件` : ''}`}
              aria-pressed={key === selected}
            >
              <span className="month-date">{d.getDate()}</span>
              {items.slice(0, 2).map((e) => (
                <span key={e.id} className="month-chip">
                  {e.all_day ? '' : `${toLocalInput(e.start).slice(11, 16)} `}
                  {e.summary}
                </span>
              ))}
              {items.length > 2 && <span className="month-more">ほか{items.length - 2}件</span>}
            </button>
          )
        })}
      </div>

      <div className="month-detail">
        <div className="panel-head">
          <h3>{formatDay(selected)}の予定</h3>
          <button className="btn small primary" onClick={() => onAdd(selected)}>
            この日に予定を追加
          </button>
        </div>
        {form}
        {selectedEvents.length === 0 ? (
          <p className="hint">予定はありません。</p>
        ) : (
          <EventList events={selectedEvents} onEdit={onEdit} onDelete={onDelete} onError={onError} hideDay />
        )}
      </div>
      <p className="hint">
        予定はこの PC の、あなたの Windows ユーザーのデータにだけ暗号化して保存されます。ほかの人と共有・公開する機能はありません。
      </p>
    </div>
  )
}

// ===================== 連携 =====================

function ConnectionPanel({
  status,
  onChanged,
  onError,
  reload,
}: {
  status: CalendarStatus | null
  onChanged: (s: CalendarStatus) => void
  onError: (m: string) => void
  reload: () => Promise<void>
}) {
  const [waiting, setWaiting] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // Google の同意画面（別タブ）での操作が終わるまで、連携状態を確認し続ける
  useEffect(() => {
    if (!waiting) return
    const started = Date.now()
    const id = window.setInterval(() => {
      if (Date.now() - started > 5 * 60_000) setWaiting(false)
      void reload()
    }, 3000)
    return () => window.clearInterval(id)
  }, [waiting, reload])

  useEffect(() => {
    if (status?.connected) setWaiting(false)
  }, [status?.connected])

  const run = async (fn: () => Promise<CalendarStatus>) => {
    onError('')
    try {
      onChanged(await fn())
    } catch (err) {
      onError(errorMessage(err))
    }
  }

  const connect = async () => {
    onError('')
    try {
      const { url } = await api.startCalendarAuth()
      window.open(url, '_blank', 'noopener,noreferrer')
      setWaiting(true)
    } catch (err) {
      onError(errorMessage(err))
    }
  }

  if (!status) return <div className="panel">読み込み中…</div>

  return (
    <div className="panel">
      <h2>Google カレンダー連携</h2>
      {status.connected ? (
        <>
          <p className="ok-text">連携しています（メインのカレンダー）。</p>
          {status.last_error && <p className="warn-text">最後の同期でエラー: {status.last_error}</p>}
          <div className="actions wrap">
            <button
              className="btn small"
              onClick={() => {
                if (window.confirm('Google カレンダーとの連携を解除しますか？')) void run(api.disconnectCalendar)
              }}
            >
              連携を解除
            </button>
          </div>
        </>
      ) : status.source === 'bundled' ? (
        <>
          <p>Google アカウントでログインすると、予定を見たり、会話から予定を追加したりできるようになります。</p>
          <div className="actions wrap">
            <button className="btn primary google-login" onClick={() => void connect()}>
              Google でログインして連携
            </button>
          </div>
          {waiting && (
            <p className="hint" role="status">
              開いたタブでログインと許可が終わるのを待っています…
            </p>
          )}
          <p className="hint">
            使うのは「予定の表示と編集」の権限だけです。予定の追加・変更・削除は、このアプリで「承認して実行」を押したときだけ行われます。
            ログイン情報（トークン）は暗号化して、この PC にだけ保存されます。
            「このアプリは Google で確認されていません」と表示された場合は、「詳細」→「（アプリ名）に移動」で進めます。
          </p>
        </>
      ) : !status.configured ? (
        <>
          <p>
            このアプリにはまだ Google の登録ファイルが入っていません。管理者がファイルを置けば、Google でログインするだけで連携できるようになります（
            <code>docs/GOOGLE_CALENDAR.md</code>）。
          </p>
          <details className="advanced">
            <summary>自分で登録して使う</summary>
          <p>
            あなたの Google アカウントで「OAuth クライアント」を1度だけ作成し、その JSON ファイルを登録します。
          </p>
          <ol className="guide">
            <li>
              <a href="https://console.cloud.google.com/projectcreate" target="_blank" rel="noopener noreferrer">
                Google Cloud コンソール
              </a>
              で新しいプロジェクトを作成します（無料）。
            </li>
            <li>「API とサービス › ライブラリ」で <strong>Google Calendar API</strong> を有効にします。</li>
            <li>
              「OAuth 同意画面」で、ユーザーの種類「外部」を選び、アプリ名と自分のメールアドレスを入力します。
              「テストユーザー」に自分の Google アカウントを追加します。
            </li>
            <li>
              「認証情報 › 認証情報を作成 › OAuth クライアント ID」で、種類 <strong>「デスクトップアプリ」</strong> を選んで作成し、JSON
              をダウンロードします。
            </li>
            <li>ダウンロードした JSON ファイルを下で選択します（暗号化してこのPCに保存されます）。</li>
          </ol>
          <label className="field">
            <span>OAuth クライアントの JSON ファイル</span>
            <input
              ref={inputRef}
              type="file"
              accept=".json,application/json"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) void run(() => api.uploadCalendarClient(file))
                if (inputRef.current) inputRef.current.value = ''
              }}
            />
          </label>
          </details>
        </>
      ) : (
        <>
          <p>OAuth クライアント（{status.client_id_hint}）を登録済みです。Google のページで、カレンダーへのアクセスを許可してください。</p>
          <p className="hint">
            要求する権限は「予定の表示と編集（calendar.events）」だけです。予定の追加・変更・削除は、このアプリで承認したときだけ実行されます。
            「このアプリは Google で確認されていません」と表示された場合は、自分で作成したクライアントなので「続行」で進めます。
          </p>
          <div className="actions wrap">
            <button
              className="btn small"
              onClick={() => {
                if (window.confirm('登録した OAuth クライアントを削除しますか？')) void run(api.removeCalendarClient)
              }}
            >
              クライアントを削除
            </button>
            <button className="btn primary" onClick={() => void connect()}>
              Google と連携
            </button>
          </div>
          {waiting && (
            <p className="hint" role="status">
              開いたタブで許可が終わるのを待っています…
            </p>
          )}
        </>
      )}
    </div>
  )
}

// ===================== 予定一覧・フォーム =====================

function EventList({
  events,
  onEdit,
  onDelete,
  onError,
  hideDay = false,
}: {
  events: CalendarEvent[]
  onEdit: (e: CalendarEvent) => void
  onDelete: (e: CalendarEvent) => void
  onError: (m: string) => void
  /** 1日分だけを表示するときは、日付の見出しを出さない */
  hideDay?: boolean
}) {
  const [overrides, setOverrides] = useState<Record<string, number | null>>({})
  const groups = new Map<string, CalendarEvent[]>()
  for (const e of events) {
    const key = dayKey(e.start)
    groups.set(key, [...(groups.get(key) ?? []), e])
  }

  const changeNotify = async (event: CalendarEvent, value: string) => {
    const minutes = value === '' ? null : Number(value)
    try {
      await api.setEventNotify(event.id, minutes)
      setOverrides((prev) => ({ ...prev, [event.id]: minutes }))
    } catch (err) {
      onError(errorMessage(err))
    }
  }

  return (
    <div className="event-days">
      {[...groups.entries()].map(([day, items]) => (
        <div key={day} className="event-day">
          {!hideDay && <h3>{formatDay(day)}</h3>}
          <ul className="memory-list">
            {items.map((e) => {
              const notify = e.id in overrides ? overrides[e.id] : e.notify_minutes
              return (
                <li key={e.id} className="memory-item panel event-item">
                  <div>
                    <p className="memory-content">
                      <strong>{e.summary}</strong>
                    </p>
                    <span className="hint">
                      {formatRange(e)}
                      {e.location && ` ・ ${e.location}`}
                    </span>
                  </div>
                  <div className="event-actions">
                    <label className="inline-field">
                      <span className="hint">通知</span>
                      <select value={notify == null ? '' : String(notify)} onChange={(ev) => void changeNotify(e, ev.target.value)}>
                        {NOTIFY_OPTIONS.map(([v, label]) => (
                          <option key={v} value={v}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button className="btn small" onClick={() => onEdit(e)}>
                      変更
                    </button>
                    <button className="btn small danger" onClick={() => onDelete(e)}>
                      削除
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </div>
  )
}

function defaultDraft(initial: CalendarEvent | null, day: string | null = null): EventDraft {
  if (initial) {
    return {
      summary: initial.summary,
      all_day: initial.all_day,
      start: initial.all_day ? initial.start : toLocalInput(initial.start),
      end: initial.all_day ? initial.end : toLocalInput(initial.end),
      location: initial.location,
      description: initial.description,
      reminder_minutes: null,
    }
  }
  const start = new Date()
  start.setHours(start.getHours() + 1, 0, 0, 0)
  // 月の表示で日付を選んで追加するときは、その日の同じ時刻にする
  if (day) {
    const [y, m, d] = day.split('-').map(Number)
    start.setFullYear(y, m - 1, d)
  }
  const end = new Date(start.getTime() + 60 * 60 * 1000)
  return { summary: '', all_day: false, start: toLocalInput(start), end: toLocalInput(end), location: '', description: '', reminder_minutes: null }
}

function EventForm({
  initial,
  day = null,
  local,
  onCancel,
  onSubmit,
}: {
  initial: CalendarEvent | null
  /** 新しい予定の日付（月の表示で選んだ日） */
  day?: string | null
  /** アプリ内カレンダー（保存したらすぐ反映）か、Google カレンダー（承認してから反映）か */
  local: boolean
  onCancel: () => void
  onSubmit: (draft: EventDraft) => void
}) {
  const [draft, setDraft] = useState<EventDraft>(() => defaultDraft(initial, day))
  const set = <K extends keyof EventDraft>(key: K, value: EventDraft[K]) => setDraft((d) => ({ ...d, [key]: value }))

  const toggleAllDay = (allDay: boolean) =>
    setDraft((d) => ({
      ...d,
      all_day: allDay,
      start: allDay ? d.start.slice(0, 10) : `${d.start.slice(0, 10)}T09:00`,
      end: allDay ? d.end.slice(0, 10) : `${d.end.slice(0, 10)}T10:00`,
    }))

  return (
    <form
      className="panel event-form"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit(draft)
      }}
    >
      <h3>{initial ? '予定を変更' : '予定を追加'}</h3>
      <label className="field">
        <span>タイトル</span>
        <input value={draft.summary} maxLength={200} required onChange={(e) => set('summary', e.target.value)} />
      </label>
      <label className="checkbox">
        <input type="checkbox" checked={draft.all_day} onChange={(e) => toggleAllDay(e.target.checked)} />
        終日
      </label>
      <div className="form-row">
        <label className="field">
          <span>開始</span>
          <input
            type={draft.all_day ? 'date' : 'datetime-local'}
            value={draft.start}
            required
            onChange={(e) => set('start', e.target.value)}
          />
        </label>
        <label className="field">
          <span>終了</span>
          <input
            type={draft.all_day ? 'date' : 'datetime-local'}
            value={draft.end}
            required
            onChange={(e) => set('end', e.target.value)}
          />
        </label>
      </div>
      <label className="field">
        <span>場所</span>
        <input value={draft.location} maxLength={200} onChange={(e) => set('location', e.target.value)} />
      </label>
      <label className="field">
        <span>メモ</span>
        <textarea value={draft.description} maxLength={2000} rows={2} onChange={(e) => set('description', e.target.value)} />
      </label>
      <label className="field">
        <span>{local ? '通知' : 'Google カレンダーのリマインダー'}</span>
        <select
          value={draft.reminder_minutes == null ? '' : String(draft.reminder_minutes)}
          onChange={(e) => set('reminder_minutes', e.target.value === '' ? null : Number(e.target.value))}
        >
          <option value="">{local ? '既定（通知の設定に合わせる）' : 'カレンダーの既定'}</option>
          {NOTIFY_OPTIONS.filter(([v]) => v !== '' && v !== '-1').map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {!local && (
        <p className="hint">「確認へ進む」を押すと承認待ちの操作が作られます。承認するまで Google カレンダーは変更されません。</p>
      )}
      <div className="actions">
        <button type="button" className="btn" onClick={onCancel}>
          キャンセル
        </button>
        <button type="submit" className="btn primary">
          {local ? '保存' : '確認へ進む'}
        </button>
      </div>
    </form>
  )
}

// ===================== 通知 =====================

function NotificationPanel() {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  useEffect(() => {
    api.getSettings().then(setSettings, (err) => setMessage({ kind: 'error', text: errorMessage(err) }))
  }, [])

  const save = async (values: Partial<AppSettings>) => {
    setMessage(null)
    try {
      setSettings(await api.updateSettings(values))
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  const test = async () => {
    setMessage(null)
    try {
      await api.testNotification()
      setMessage({ kind: 'ok', text: 'テスト通知を送りました。画面の右下に表示されます。' })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  if (!settings) return null
  return (
    <div className="panel">
      <h2>通知</h2>
      <div className="banner warn" role="note">
        通知はこのPCが起動していて、バックグラウンドサービスが動いているときだけ表示されます。
        シャットダウン・スリープ中の予定は通知できません（起動後15分以内のものは遅れて1回だけ通知します）。
      </div>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={settings.notifications_enabled}
          onChange={(e) => void save({ notifications_enabled: e.target.checked })}
        />
        予定を Windows のデスクトップ通知で知らせる
      </label>
      <label className="field">
        <span>通知のタイミング（予定ごとに設定していない場合）</span>
        <select
          value={settings.default_reminder_minutes}
          onChange={(e) => void save({ default_reminder_minutes: Number(e.target.value) })}
        >
          {NOTIFY_OPTIONS.filter(([v]) => v !== '' && v !== '-1').map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={settings.calendar_ai_proposals}
          onChange={(e) => void save({ calendar_ai_proposals: e.target.checked })}
        />
        会話の中で、AIが予定の追加・変更・削除を提案する（実行は承認後のみ）
      </label>
      <div className="actions wrap">
        <button className="btn small" onClick={() => void test()}>
          テスト通知
        </button>
      </div>
      {message && (
        <p className={message.kind === 'ok' ? 'ok-text' : 'error-text'} role={message.kind === 'error' ? 'alert' : 'status'}>
          {message.text}
        </p>
      )}
    </div>
  )
}

// ===================== バックグラウンドサービス =====================

function ServicePanel() {
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [stopped, setStopped] = useState(false)

  const load = useCallback(async () => {
    try {
      setStatus(await api.systemStatus())
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const toggle = async (enabled: boolean) => {
    setMessage(null)
    try {
      await api.setAutostart(enabled)
      await load()
      setMessage({
        kind: 'ok',
        text: enabled ? 'Windows にサインインしたとき、サービスが自動で起動します（ブラウザーは開きません）。' : '自動起動をオフにしました。',
      })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  const restart = async () => {
    setMessage(null)
    try {
      await api.restartServer()
      setMessage({ kind: 'ok', text: '再起動しています…' })
      // 新しいプロセスが起動するまで待ってから画面を読み込み直す
      const started = Date.now()
      const poll = window.setInterval(async () => {
        try {
          const s = await api.systemStatus()
          if (s.pid !== status?.pid) {
            window.clearInterval(poll)
            window.location.reload()
          }
        } catch {
          if (Date.now() - started > 60_000) {
            window.clearInterval(poll)
            setMessage({ kind: 'error', text: '再起動を確認できませんでした。start.bat から起動してください。' })
          }
        }
      }, 1500)
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  const stop = async () => {
    if (!window.confirm('バックグラウンドサービスを停止しますか？停止中は会話も通知もできません。')) return
    try {
      await api.stopServer()
      setStopped(true)
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  if (stopped) {
    return (
      <div className="panel">
        <h2>バックグラウンドサービス</h2>
        <p className="warn-text" role="status">
          サービスを停止しました。再開するには start.bat を実行するか、PCに再度サインインしてください（自動起動がオンの場合）。
        </p>
      </div>
    )
  }
  if (!status) return null
  return (
    <div className="panel">
      <h2>バックグラウンドサービス</h2>
      <p className="hint">
        予定の通知はバックグラウンドで動くサーバーが行います。自動起動をオンにすると、Windows のサインイン時にサーバーだけが起動します（ブラウザーは開きません）。
      </p>
      <dl className="summary compact">
        <div>
          <dt>状態</dt>
          <dd>
            動作中（{status.background ? 'バックグラウンド' : 'コンソール'}・プロセス {status.pid}・起動から{' '}
            {Math.floor(status.uptime_seconds / 60)} 分）
          </dd>
        </div>
      </dl>
      <label className="checkbox">
        <input type="checkbox" checked={status.autostart} onChange={(e) => void toggle(e.target.checked)} />
        Windows のサインイン時に自動で起動する
      </label>
      <div className="actions wrap">
        <button className="btn small" onClick={() => void restart()}>
          再起動
        </button>
        <button className="btn small danger" onClick={() => void stop()}>
          停止
        </button>
      </div>
      {message && (
        <p className={message.kind === 'ok' ? 'ok-text' : 'error-text'} role={message.kind === 'error' ? 'alert' : 'status'}>
          {message.text}
        </p>
      )}
    </div>
  )
}
