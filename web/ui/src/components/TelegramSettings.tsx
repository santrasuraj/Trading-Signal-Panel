// Telegram choices (scanner/notify_settings.py): the 08:45 morning brief (Calendar page) and live setups while the
// market is open (Live setups page). Both are off until switched on; Telegram needs TELEGRAM_BOT_TOKEN / CHAT_ID in .env.

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Send } from 'lucide-react'
import { fetchJson, isFailure } from '@/api/client'
import { Button, Card, Switch } from '@/components/ui'

interface NotifySettings { brief: boolean; setups: { on: boolean; scope: 'mine' | 'all'; kinds: string[] }; telegram: boolean }

function useNotify() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['notify-settings'], queryFn: () => fetchJson<NotifySettings>('/api/notify-settings'), staleTime: 60_000 })
  const put = useMutation({ mutationFn: (v: Partial<NotifySettings>) => fetchJson<NotifySettings>('/api/notify-settings', { method: 'PUT', body: JSON.stringify(v) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['notify-settings'] }) } })
  return { q, put }
}

export function SetupsTelegram({ scope }: { scope: 'mine' | 'all' }) {
  const { q, put } = useNotify()
  const d = q.data
  if (!d) return null
  return (
    <span className="flex items-center gap-2 text-xs" title={d.telegram ? 'New setups go to your Telegram every 2 minutes while the live service runs' : 'Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env first'}>
      <Switch checked={d.setups.on} disabled={!d.telegram} onChange={(on) => put.mutate({ setups: { ...d.setups, on, scope } })} label={`Telegram${d.setups.on ? ` (${d.setups.scope === 'mine' ? 'my stocks' : 'all'})` : ''}`} />
    </span>
  )
}

export function BriefCard() {
  const { q, put } = useNotify()
  const [show, setShow] = useState(false)
  const preview = useQuery({ queryKey: ['brief'], queryFn: () => fetchJson<{ text: string }>('/api/brief'), enabled: show, staleTime: 5 * 60_000 })
  const send = useMutation({ mutationFn: () => fetchJson<{ sent: boolean; detail: string }>('/api/brief/send', { method: 'POST', body: '{}' }) })
  const d = q.data
  return (
    <Card title="Morning brief on Telegram" subtitle="At 08:45 on trading days, with the login reminder: today's events, your stocks' results, ex-dates and filings, the tested BUY / SELL list and stops hit"
      right={d ? <Switch checked={d.brief} disabled={!d.telegram} onChange={(on) => put.mutate({ brief: on })} label={d.brief ? 'On' : 'Off'} /> : undefined}>
      {d && !d.telegram && <p className="mb-2 text-xs text-warn">Telegram isn't set up: add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env.</p>}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="subtle" onClick={() => setShow(!show)}>{show ? 'Hide preview' : 'Preview today\'s brief'}</Button>
        <Button size="sm" variant="subtle" icon={<Send className="h-3.5 w-3.5" />} disabled={!d?.telegram} loading={send.isPending} onClick={() => send.mutate()}>Send now</Button>
        {send.data && <span className={send.data.sent ? 'text-xs text-profit' : 'text-xs text-loss'}>{send.data.sent ? 'Sent to Telegram.' : send.data.detail}</span>}
        {send.error && <span className="text-xs text-loss">{isFailure(send.error) ? send.error.message : 'Not sent.'}</span>}
      </div>
      {show && <pre className="mt-2 whitespace-pre-wrap rounded bg-raised p-2 text-xs text-fg">{preview.data?.text ?? 'Building…'}</pre>}
    </Card>
  )
}
