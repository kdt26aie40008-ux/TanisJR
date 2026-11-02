import { SSEParser } from '../lib/sse'
import type {
  AppSettings,
  Avatar,
  CalendarEvent,
  CalendarOperation,
  CalendarStatus,
  EventDraft,
  SystemStatus,
  TrainingEnvironment,
  TrainingExample,
  TrainingParams,
  TrainingRun,
  SpeakersResponse,
  SttStatus,
  Transcript,
  ChatEvent,
  ChatMessage,
  ConversationDetail,
  ConversationSummary,
  Health,
  Memory,
  MemoryCategory,
  MemoryStats,
  ModelStatus,
  ProfileEntry,
  PullEvent,
  SetupQuestionsResponse,
} from './types'

/** 画面に表示できる日本語メッセージを持つエラー。 */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number,
  ) {
    super(message)
  }
}

const NETWORK_ERROR = 'サーバーに接続できません。バックエンドが起動しているか確認してください。'

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body = await response.json()
    const detail = body?.detail
    if (detail && typeof detail.message === 'string') {
      return new ApiError(detail.message, detail.code ?? 'error', response.status)
    }
  } catch {
    // JSON 以外の応答
  }
  return new ApiError(`サーバーでエラーが発生しました（${response.status}）。`, 'http_error', response.status)
}

async function send(path: string, init: RequestInit = {}): Promise<Response> {
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(NETWORK_ERROR, 'network_error', 0)
  }
  if (!response.ok) throw await toApiError(response)
  return response
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  return (await send(path, init)).json() as Promise<T>
}

async function* stream<T>(path: string, body: unknown, signal?: AbortSignal): AsyncGenerator<T> {
  const response = await send(path, { method: 'POST', body: JSON.stringify(body), signal })
  if (!response.body) throw new ApiError('応答を読み取れませんでした。', 'no_body', 0)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const parser = new SSEParser<T>()
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      yield* parser.feed(decoder.decode(value, { stream: true }))
    }
  } finally {
    reader.releaseLock()
  }
}

function body(value: unknown, method = 'POST'): RequestInit {
  return { method, body: JSON.stringify(value) }
}

export const api = {
  health: () => json<Health>('/api/health'),
  setupStatus: () => json<{ completed: boolean }>('/api/setup/status'),
  setupQuestions: () => json<SetupQuestionsResponse>('/api/setup/questions'),
  completeSetup: (body: { consent: boolean; answers: string[]; ai_name: string }) =>
    json<{ completed: boolean; ai_name: string }>('/api/setup/complete', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getSettings: () => json<AppSettings>('/api/settings'),
  updateSettings: (values: Partial<AppSettings>) =>
    json<AppSettings>('/api/settings', { method: 'PUT', body: JSON.stringify(values) }),
  getProfile: () => json<ProfileEntry[]>('/api/profile'),
  updateProfile: (key: string, content: string) =>
    json<ProfileEntry>('/api/profile', { method: 'PUT', body: JSON.stringify({ key, content }) }),
  modelStatus: () => json<ModelStatus>('/api/models/status'),
  pullModel: (model: string, signal?: AbortSignal) =>
    stream<PullEvent>('/api/models/pull', { model, confirmed: true }, signal),
  chat: (messages: ChatMessage[], conversationId: string | null, signal?: AbortSignal) =>
    stream<ChatEvent>(
      '/api/chat',
      conversationId ? { messages, conversation_id: conversationId } : { messages },
      signal,
    ),

  // ----- 記憶 -----
  memories: (params: { status?: 'active' | 'pending'; q?: string; category?: string } = {}) => {
    const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][])
    return json<Memory[]>(`/api/memories${query.size ? `?${query}` : ''}`)
  },
  memoryStats: () => json<MemoryStats>('/api/memories/stats'),
  createMemory: (value: { content: string; category: MemoryCategory; importance: number }) =>
    json<Memory>('/api/memories', body(value)),
  updateMemory: (id: string, value: Partial<Pick<Memory, 'content' | 'category' | 'importance'>>) =>
    json<Memory>(`/api/memories/${id}`, body(value, 'PUT')),
  deleteMemory: (id: string) => json<{ deleted: boolean }>(`/api/memories/${id}`, { method: 'DELETE' }),
  approveMemory: (id: string, value?: { content: string }) =>
    json<Memory>(`/api/memories/${id}/approve`, value ? body(value) : { method: 'POST' }),
  rejectMemory: (id: string) => json<{ deleted: boolean }>(`/api/memories/${id}/reject`, { method: 'POST' }),
  reindexMemories: () =>
    json<{ removed_orphans: number; indexed: number; unindexed: number }>('/api/memories/reindex', { method: 'POST' }),

  // ----- 会話履歴 -----
  conversations: () => json<ConversationSummary[]>('/api/conversations'),
  conversation: (id: string) => json<ConversationDetail>(`/api/conversations/${id}`),
  createConversation: (messages: ChatMessage[]) => json<ConversationSummary>('/api/conversations', body({ messages })),
  deleteConversation: (id: string, deleteMemories: boolean) =>
    json<{ deleted: boolean }>(`/api/conversations/${id}?delete_memories=${deleteMemories}`, { method: 'DELETE' }),

  // ----- バックアップ -----
  createBackup: async (passphrase: string) => {
    const response = await send('/api/backup', body({ passphrase }))
    const disposition = response.headers.get('Content-Disposition') ?? ''
    const filename = disposition.match(/filename="([^"]+)"/)?.[1] ?? 'twin-backup.twinbak'
    return { blob: await response.blob(), filename }
  },
  restoreBackup: (passphrase: string, data: string) =>
    json<{ restored: boolean; backup_created_at: string }>('/api/backup/restore', body({ passphrase, data })),

  // ----- 音声 -----
  sttStatus: () => json<SttStatus>('/api/speech/stt/status'),
  warmupStt: () => json<{ started: boolean }>('/api/speech/stt/warmup', { method: 'POST' }),
  downloadWhisper: (model: string) =>
    json<{ started: boolean }>('/api/speech/stt/models/download', body({ model, confirmed: true })),
  transcribe: (audio: Blob) =>
    json<Transcript>('/api/speech/stt', {
      method: 'POST',
      body: audio,
      headers: { 'Content-Type': audio.type || 'application/octet-stream' },
    }),
  speakers: () => json<SpeakersResponse>('/api/speech/tts/speakers'),
  speakerPolicy: (uuid: string) => json<{ policy: string }>(`/api/speech/tts/speakers/${uuid}/policy`),
  acknowledgeSpeaker: (uuid: string) =>
    json<{ acknowledged: boolean }>('/api/speech/tts/acknowledge', body({ speaker_uuid: uuid })),
  synthesize: async (text: string, speaker?: number, signal?: AbortSignal) => {
    const response = await send('/api/speech/tts', { ...body(speaker === undefined ? { text } : { text, speaker }), signal })
    return response.arrayBuffer()
  },

  // ----- アバター -----
  avatars: () => json<{ avatars: Avatar[]; active_id: string | null }>('/api/avatars'),
  uploadAvatar: (file: File, name: string, placeholder: boolean) =>
    json<Avatar>(`/api/avatars?${new URLSearchParams({ name, placeholder: String(placeholder) })}`, {
      method: 'POST',
      body: file,
      headers: { 'Content-Type': 'application/octet-stream' },
    }),
  updateAvatar: (id: string, value: { name?: string; is_placeholder?: boolean }) =>
    json<Avatar>(`/api/avatars/${id}`, body(value, 'PUT')),
  activateAvatar: (id: string) => json<{ active_id: string }>(`/api/avatars/${id}/activate`, { method: 'POST' }),
  deleteAvatar: (id: string) => json<{ deleted: boolean }>(`/api/avatars/${id}`, { method: 'DELETE' }),
  avatarFileUrl: (id: string) => `/api/avatars/${id}/file`,

  // ----- カレンダー -----
  calendarStatus: () => json<CalendarStatus>('/api/calendar/status'),
  uploadCalendarClient: (file: File) =>
    json<CalendarStatus>('/api/calendar/client', { method: 'POST', body: file, headers: { 'Content-Type': 'application/json' } }),
  removeCalendarClient: () => json<CalendarStatus>('/api/calendar/client', { method: 'DELETE' }),
  startCalendarAuth: () => json<{ url: string }>('/api/calendar/auth/start', { method: 'POST' }),
  disconnectCalendar: () => json<CalendarStatus>('/api/calendar/disconnect', { method: 'POST' }),
  calendarEvents: (days = 14) => json<CalendarEvent[]>(`/api/calendar/events?days=${days}`),
  setEventNotify: (eventId: string, minutes: number | null) =>
    json<{ minutes: number | null }>(`/api/calendar/events/${encodeURIComponent(eventId)}/notify`, body({ minutes }, 'PUT')),
  calendarOperations: (status: 'pending' | 'all' = 'pending') =>
    json<CalendarOperation[]>(`/api/calendar/operations?status=${status}`),
  proposeCalendarOperation: (value: { action: 'create' | 'update' | 'delete'; event_id?: string; draft?: EventDraft }) =>
    json<CalendarOperation>('/api/calendar/operations', body(value)),
  approveCalendarOperation: (id: string) =>
    json<CalendarOperation>(`/api/calendar/operations/${id}/approve`, { method: 'POST' }),
  rejectCalendarOperation: (id: string) => json<CalendarOperation>(`/api/calendar/operations/${id}/reject`, { method: 'POST' }),
  testNotification: () => json<{ shown: boolean }>('/api/calendar/notifications/test', { method: 'POST' }),

  // ----- 追加学習 -----
  trainingExamples: (status?: 'pending' | 'approved' | 'rejected') =>
    json<{ examples: TrainingExample[]; counts: Record<'pending' | 'approved' | 'rejected', number> }>(
      `/api/training/examples${status ? `?status=${status}` : ''}`,
    ),
  addTrainingExample: (user_text: string, assistant_text: string) =>
    json<TrainingExample>('/api/training/examples', body({ user_text, assistant_text })),
  trainingFromConversation: (conversation_id: string) =>
    json<{ created: number }>('/api/training/examples/from-conversation', body({ conversation_id })),
  updateTrainingExample: (id: string, value: { user_text?: string; assistant_text?: string }) =>
    json<TrainingExample>(`/api/training/examples/${id}`, body(value, 'PUT')),
  decideTrainingExample: (id: string, decision: 'approve' | 'reject' | 'pending') =>
    json<TrainingExample>(`/api/training/examples/${id}/${decision}`, { method: 'POST' }),
  deleteTrainingExample: (id: string) => json<{ deleted: boolean }>(`/api/training/examples/${id}`, { method: 'DELETE' }),
  dedupeTrainingExamples: () => json<{ removed: number }>('/api/training/examples/dedupe', { method: 'POST' }),
  exportTrainingExamples: async () => (await send('/api/training/examples/export', body({ confirmed: true }))).blob(),
  distill: (limit: number) => json<{ created: number; teacher: string }>('/api/training/distill', body({ limit })),
  trainingEnvironment: () => json<TrainingEnvironment>('/api/training/environment'),
  startTraining: (params: TrainingParams) => json<TrainingRun>('/api/training/runs', body({ ...params, confirmed: true })),
  trainingRuns: () => json<{ runs: TrainingRun[]; model: string }>('/api/training/runs'),
  trainingLog: (id: string) => json<{ log: string }>(`/api/training/runs/${id}/log?lines=120`),
  cancelTraining: (id: string) => json<TrainingRun>(`/api/training/runs/${id}/cancel`, { method: 'POST' }),
  activateTraining: (id: string) => json<TrainingRun>(`/api/training/runs/${id}/activate`, { method: 'POST' }),
  revertTraining: () => json<{ model: string }>('/api/training/revert', { method: 'POST' }),
  deleteTraining: (id: string) => json<{ deleted: boolean }>(`/api/training/runs/${id}`, { method: 'DELETE' }),

  // ----- バックグラウンドサービス -----
  systemStatus: () => json<SystemStatus>('/api/system/status'),
  setAutostart: (enabled: boolean) => json<{ autostart: boolean }>('/api/system/autostart', body({ enabled }, 'PUT')),
  restartServer: () => json<{ restarting: boolean }>('/api/system/restart', { method: 'POST' }),
  stopServer: () => json<{ stopping: boolean }>('/api/system/stop', { method: 'POST' }),
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return '予期しないエラーが発生しました。'
}
