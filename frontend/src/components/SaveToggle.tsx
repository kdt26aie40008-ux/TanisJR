import { useConversation } from '../state/ConversationContext'

export function SaveToggle() {
  const { saveEnabled, conversationId, streaming, savingToggle, toggleSave } = useConversation()
  const status = !saveEnabled ? 'この会話は保存されません' : conversationId ? '保存中' : '次の送信から保存します'
  return (
    <>
      <label className={`switch${saveEnabled ? ' on' : ''}`}>
        <input
          type="checkbox"
          role="switch"
          checked={saveEnabled}
          disabled={streaming || savingToggle}
          onChange={(e) => void toggleSave(e.target.checked)}
        />
        <span className="switch-track" aria-hidden />
        この会話を保存
      </label>
      <span className="hint" data-testid="save-status">
        {status}
      </span>
    </>
  )
}
