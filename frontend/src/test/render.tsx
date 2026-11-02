import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { ConversationProvider } from '../state/ConversationContext'

export function renderWithConversation(ui: ReactElement) {
  return render(<ConversationProvider>{ui}</ConversationProvider>)
}
