export interface SetupQuestion {
  key: string
  text: string
}

export interface ConsentInfo {
  version: string
  purpose: string
  stored_items: string[]
  notes: string[]
}

export interface SetupQuestionsResponse {
  questions: SetupQuestion[]
  consent: ConsentInfo
}

export interface AppSettings {
  ai_name: string
  model: string
  fallback_model: string
  temperature: number
  num_ctx: number
  think: boolean
  save_conversations_default: boolean
  auto_extract: boolean
  embedding_model: string
  rag_max_results: number
  rag_max_distance: number
  stt_model: string
  stt_device: 'cpu' | 'cuda'
  stt_auto_send: boolean
  voice_auto_stop: boolean
  voice_silence_ms: number
  voice_handsfree: boolean
  behavior_nod: boolean
  behavior_gaze: boolean
  behavior_backchannel: boolean
  behavior_barge_in: boolean
  behavior_sentence_emotion: boolean
  language: LanguageCode
  proactive_enabled: boolean
  proactive_morning: boolean
  proactive_event_minutes: number
  proactive_idle_hours: number
  quiet_start: string
  quiet_end: string
  wake_enabled: boolean
  wake_reading: string
  tts_speaker: number | null
  tts_speed: number
  tts_auto_read: boolean
  tts_engine_autostart: boolean
  tts_acknowledged_speakers: string[]
  avatar_id: string
  notifications_enabled: boolean
  default_reminder_minutes: number
  calendar_ai_proposals: boolean
}

export type LanguageCode = 'ja' | 'en' | 'zh' | 'ko' | 'es' | 'fr' | 'de'

export const LANGUAGE_NAMES: Record<LanguageCode, string> = {
  ja: '日本語',
  en: '英語',
  zh: '中国語',
  ko: '韓国語',
  es: 'スペイン語',
  fr: 'フランス語',
  de: 'ドイツ語',
}

export interface WakeStatus {
  enabled: boolean
  /** 「あなたのこと」がすべて入力されているか */
  ready: boolean
  /** まだ入力されていない項目 */
  missing: string[]
}

export interface CalendarStatus {
  configured: boolean
  /** bundled: アプリに同梱された登録（ログインするだけで連携できる）/ own: この PC で自分で登録したもの */
  source: 'bundled' | 'own' | null
  connected: boolean
  client_id_hint: string | null
  redirect_uri: string
  last_sync_at: string | null
  last_error: string | null
}

export interface CalendarEvent {
  id: string
  summary: string
  all_day: boolean
  start: string
  end: string
  location: string
  description: string
  html_link: string
  notify_minutes: number | null
}

export interface EventDraft {
  summary: string
  all_day: boolean
  start: string
  end: string
  location: string
  description: string
  reminder_minutes: number | null
}

export interface CalendarOperation {
  id: string
  action: 'create' | 'update' | 'delete'
  event_id: string | null
  draft: EventDraft | null
  target: CalendarEvent | null
  source: 'user' | 'ai'
  status: 'pending' | 'done' | 'rejected' | 'failed'
  error: string | null
  result_event_id: string | null
  created_at: string
  decided_at: string | null
}

export interface TrainingExample {
  id: string
  source: 'conversation' | 'manual' | 'distill'
  conversation_id: string | null
  user_text: string
  assistant_text: string
  status: 'pending' | 'approved' | 'rejected'
  created_at: string
  updated_at: string
  warnings: string[]
}

export interface TrainingBase {
  id: string
  label: string
  hf_repo: string
  ollama_model: string
  quantize_4bit: boolean
  size_gb: number
  note: string
  downloaded: boolean
}

export interface TrainingEnvironment {
  training_python: boolean
  converter: boolean
  bases: TrainingBase[]
  min_examples: number
  approved_examples: number
  running: string | null
}

export interface TrainingParams {
  base: string
  epochs: number
  learning_rate: number
  lora_r: number
  lora_alpha: number
  max_seq_len: number
  grad_accum: number
}

export interface TrainingRun {
  id: string
  base: string
  status: 'running' | 'succeeded' | 'failed' | 'cancelled'
  example_count: number
  params: TrainingParams
  metrics: {
    eval_loss_before: number | null
    eval_loss_after: number | null
    train_examples: number
    eval_examples?: number
    train_seconds?: number
    peak_gpu_memory_gb?: number
    samples: { prompt: string; before: string; after: string }[]
  } | null
  error: string | null
  ollama_model: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  progress: { phase: string; step: number; total_steps: number; loss: number | null; eta_seconds: number | null; gpu_memory_gb?: number } | null
  active: boolean
}

export interface SystemStatus {
  pid: number
  uptime_seconds: number
  background: boolean
  autostart: boolean
  notifications_enabled: boolean
}

export interface SttStatus {
  models: { name: string; size_gb: number; description: string; recommended: boolean; installed: boolean }[]
  models_dir: string
  loaded: { model: string; device: string } | null
  download: { model: string; state: 'downloading' | 'done' | 'error'; error: string | null; downloaded_gb: number } | null
  model: string
  device: 'cpu' | 'cuda'
}

export interface Transcript {
  text: string
  duration: number
  elapsed: number
  device: string
  notice: string | null
}

export interface Speaker {
  name: string
  speaker_uuid: string
  styles: { id: number; name: string }[]
  acknowledged: boolean
}

export interface SpeakersResponse {
  available: boolean
  message: string | null
  speakers: Speaker[]
  selected: number | null
}

export interface AvatarMeta {
  name: string
  authors: string
  copyright: string
  license_url: string
  avatar_permission: string
  commercial_usage: string
  credit_required: boolean
  allow_redistribution: boolean
  modification: string
  license_name?: string
}

export interface Avatar {
  id: string
  name: string
  size: number
  is_placeholder: boolean
  vrm_version: string
  meta: AvatarMeta
  created_at: string
  /** リポジトリーに同梱された標準アバター（変更・削除不可） */
  builtin: boolean
}

export interface Health {
  status: string
  version: string
  ollama: { available: boolean; version: string | null; message: string | null }
  data_locked: boolean
  locked_reason: string | null
}

export type MemoryCategory = 'preference' | 'habit' | 'fact' | 'personal' | 'personality' | 'values' | 'other'

export interface Memory {
  id: string
  category: MemoryCategory
  content: string
  source_type: 'conversation' | 'user_manual'
  source_conversation_id: string | null
  source_conversation_title: string | null
  source_excerpt: string | null
  importance: number
  sensitivity: 'general' | 'important'
  status: 'active' | 'pending'
  confirmation_status: 'auto' | 'confirmed' | 'pending'
  indexed: boolean
  created_at: string
  updated_at: string
}

export interface MemoryStats {
  active: number
  pending: number
  unindexed: number
  embedding_model: string
  embedding_available: boolean
}

export interface ConversationSummary {
  id: string
  title: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface ConversationDetail extends ConversationSummary {
  messages: { id: number; role: 'user' | 'assistant'; content: string; created_at: string }[]
}

export interface UsedMemory {
  id: string
  content: string
  category: MemoryCategory
}

export interface ProfileEntry {
  key: string
  question: string | null
  content: string
  source: string
  importance: number
  confirmation_status: string
  created_at: string
  updated_at: string
}

export interface CatalogModel {
  name: string
  size_gb: number
  description: string
  kind: 'chat' | 'embedding'
  recommended: boolean
}

export interface ModelStatus {
  ollama_available: boolean
  message: string | null
  installed: { name: string; size_gb: number }[]
  configured_model: string
  configured_model_installed: boolean
  embedding_model: string
  embedding_model_installed: boolean
  catalog: CatalogModel[]
  storage_path: string
  free_space_gb: number | null
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export type ChatEvent =
  | { type: 'token'; content: string }
  | { type: 'thinking'; content: string }
  | { type: 'notice'; message: string }
  | { type: 'error'; code: string; message: string }
  | { type: 'memories_used'; items: UsedMemory[] }
  | { type: 'saved'; conversation_id: string }
  | { type: 'calendar_proposal'; operation: CalendarOperation }
  | { type: 'done'; model: string }

export type PullEvent =
  | { type: 'progress'; status: string; completed: number | null; total: number | null }
  | { type: 'error'; code: string; message: string }
  | { type: 'done'; model: string }
