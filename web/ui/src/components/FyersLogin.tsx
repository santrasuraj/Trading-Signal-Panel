// Fyers login (spec 6.15 paste flow). The server builds the OAuth URL and keeps the pending session; the user logs
// in on Fyers, copies the address bar and pastes it here. The auth code only ever travels in a POST body.

import { useState } from 'react'
import { ExternalLink, LogIn, Terminal } from 'lucide-react'
import { useFyersComplete, useFyersLogin, useStatus } from '@/api/hooks'
import { isFailure } from '@/api/client'
import type { FyersLoginResponse } from '@/api/types'
import { useUi } from '@/app/uiState'
import { Banner } from './feedback'
import { Button, Dialog } from './ui'
import { useToast } from './toast'

export function FyersLoginDialog() {
  const { fyersLogin, setFyersLogin } = useUi()
  const { data: s } = useStatus()
  const login = useFyersLogin()
  const complete = useFyersComplete()
  const toast = useToast()
  const [session, setSession] = useState<FyersLoginResponse | null>(null)
  const [pasted, setPasted] = useState('')
  const close = () => { setFyersLogin(false); setSession(null); setPasted(''); login.reset(); complete.reset() }
  const f = s?.fyers

  const start = (mode: 'paste' | 'window') =>
    login.mutate(mode, {
      onSuccess: (r) => {
        setSession(r)
        if (r.mode === 'paste' && r.login_url) window.open(r.login_url, '_blank', 'noopener')
      },
    })

  const finish = () =>
    complete.mutate(pasted.trim(), {
      onSuccess: (r) => {
        if (r.ok) {
          toast({ tone: 'good', title: `Logged in to Fyers${r.user_name ? ` as ${r.user_name}` : ''}`, detail: r.status?.note || 'The next scan uses Fyers real-time prices.' })
          close()
        } else {
          // The server already used up the pending login session: the user has to start again.
          toast({ tone: 'bad', title: 'Fyers did not confirm the login', detail: 'The token was saved but the profile check failed. Start the login again; if it keeps failing, check FYERS_CLIENT_ID / secret / redirect URL in .env.' })
          setSession(null)
          setPasted('')
        }
      },
    })

  const err = login.error ?? complete.error
  return (
    <Dialog
      open={fyersLogin}
      onClose={close}
      title="Log in to Fyers"
      footer={
        session?.mode === 'paste' ? (
          <>
            <Button variant="ghost" onClick={close}>Cancel</Button>
            <Button variant="primary" disabled={!pasted.trim()} loading={complete.isPending} onClick={finish}>Complete login</Button>
          </>
        ) : (
          <Button variant="ghost" onClick={close}>Close</Button>
        )
      }
    >
      <div className="space-y-4 text-[13px]">
        {f && (
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 rounded-lg border border-line bg-raised/50 p-3 text-xs">
            <span className="text-muted">App credentials</span><span className="text-right">{f.configured ? `configured (${f.client_id_masked ?? 'hidden'})` : 'missing in .env'}</span>
            <span className="text-muted">Today's login</span><span className={f.logged_in_today ? 'text-right text-profit' : 'text-right text-warn'}>{f.logged_in_today ? 'yes' : 'no'}</span>
            <span className="text-muted">Plan</span><span className="text-right capitalize">{f.plan}</span>
          </div>
        )}
        {err && (
          <Banner tone="danger">
            <div className="font-medium">{isFailure(err) ? err.message : 'Login failed'}</div>
            {isFailure(err) && err.hint && <div className="text-xs text-muted">{err.hint}</div>}
          </Banner>
        )}
        {!session ? (
          <>
            <p className="text-muted">
              Fyers tokens expire every day. Logging in lets scans use real-time Fyers prices instead of Yahoo (~15 min delayed) and lets you import your holdings.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" icon={<LogIn className="h-4 w-4" />} loading={login.isPending} disabled={f ? !f.configured : false} onClick={() => start('paste')}>Log in (paste flow)</Button>
              <Button icon={<Terminal className="h-4 w-4" />} disabled={login.isPending} onClick={() => start('window')}>Open login window (legacy)</Button>
            </div>
            {f && !f.configured && <p className="text-xs text-warn">Add FYERS_CLIENT_ID and FYERS_SECRET_KEY to .env (see README), then restart the server.</p>}
            {f && <p className="text-2xs text-faint">Redirect URL registered with your Fyers app: <span className="font-mono">{f.redirect_uri}</span>. The page it lands on may not load; that is fine.</p>}
          </>
        ) : (
          <>
            <ol className="list-decimal space-y-1 pl-5 text-muted">{session.instructions.map((i) => <li key={i}>{i}</li>)}</ol>
            {session.mode === 'paste' && (
              <>
                {session.login_url && (
                  <a href={session.login_url} target="_blank" rel="noopener noreferrer" className="link inline-flex items-center gap-1 text-xs">
                    Open the Fyers login page again <ExternalLink className="h-3 w-3" />
                  </a>
                )}
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-muted">Paste the full address from the browser bar after logging in</span>
                  <textarea value={pasted} onChange={(e) => setPasted(e.target.value)} rows={3} spellCheck={false} className="input h-auto w-full py-2 font-mono text-xs" placeholder="http://127.0.0.1:8000/?s=ok&code=200&auth_code=…&state=…" />
                </label>
              </>
            )}
          </>
        )}
      </div>
    </Dialog>
  )
}
