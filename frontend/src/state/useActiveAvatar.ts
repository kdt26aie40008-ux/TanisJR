import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { Avatar } from '../api/types'

export function useAvatars() {
  const [avatars, setAvatars] = useState<Avatar[] | null>(null)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    try {
      const data = await api.avatars()
      setAvatars(data.avatars)
      setActiveId(data.active_id)
      setError('')
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const active = avatars?.find((a) => a.id === activeId) ?? null
  return { avatars, active, activeId, error, reload }
}
