// Fyers login. One click: the server makes the login link, Fyers opens in a new tab, and when the user has logged in
// there Fyers sends that tab back to this app's callback (/fyers/callback), which saves the token; this dialog sees
// the new token and closes. When Fyers' Redirect URL points somewhere this app can't receive (e.g. Docker on port
// 8000), the same button falls back to pasting the address bar, and a one-time setup panel says how to make it one
// click. The auth code never passes through this page except in the paste fallback's POST body.

import { useEffect, useRef, useState } from 'react'
import { Check, Copy, ExternalLink, LogIn } from 'lucide-react'
import { useFyersComplete, useFyersDirectSetup, useFyersLogin, useFyersWait, useStatus } from '@/api/hooks'
import { isFailure } from '@/api/client'
import type { FyersLoginResponse, FyersStatus } from '@/api/types'
import { useUi } from '@/app/uiState'
import { Banner } from './feedback'
import { Button, Dialog, Spinner } from './ui'
import { useToast } from './toast'

type Phase = 'idle' | 'waiting' | 'paste'

function CopyField({ value }: { value: string }) {
  const [done, setDone] = useState(false)
  const copy = () => {
    void navigator.clipboard?.writeText(value).then(() => { setDone(true); setTimeout(() => setDone(false), 1500) })
  }
  return (
    <span className="flex items-center gap-1.5">
      <code className="min-w-0 flex-1 truncate rounded border border-line bg-panel px-2 py-1 font-mono text-xs" title={value}>{value}</code>
      <Button size="xs" icon={done ? <Check className="h-3.5 w-3.5 text-profit" /> : <Copy className="h-3.5 w-3.5" />} onClick={copy}>{done ? 'Copied' : 'Copy'}</Button>
    </span>
  )
}

/** How to make the button one click when Fyers' redirect lands on another program (Docker on 8000). */
function DirectSetup({ f }: { f: FyersStatus }) {
  const setup = useFyersDirectSetup()
  return (
    <div className="space-y-2 rounded-lg border border-line p-3 text-xs">
      <div className="text-[13px] font-semibold">Make it one click (one-time setup)</div>
      <p className="text-muted">
        After you log in, Fyers sends you to <span className="font-mono">{f.redirect_uri}</span>, which another program on this PC answers (Docker / WSL), so Quant Desk can't finish the login by itself.
      </p>
      <ol className="list-decimal space-y-2 pl-5 text-muted">
        <li>
          Open your app in the <a className="link inline-flex items-center gap-0.5" href="https://myapi.fyers.in/dashboard" target="_blank" rel="noopener noreferrer">Fyers API dashboard<ExternalLink className="h-3 w-3" /></a> and set its <span className="text-fg">Redirect URL</span> to:
          <div className="mt-1"><CopyField value={f.callback_url} /></div>
          <div className="mt-1 text-faint">If your Docker app uses this same Fyers app, create a second app for Quant Desk instead (free), and put its App ID and Secret in <code>.env</code>.</div>
        </li>
        <li>
          Then: <Button size="xs" variant="primary" loading={setup.isPending} onClick={() => setup.mutate()}>I've changed it in Fyers</Button>
          <span className="ml-1 text-faint">(Quant Desk saves the address in <code>.env</code>.)</span>
        </li>
      </ol>
      {setup.error && <p className="text-loss">{isFailure(setup.error) ? setup.error.message : 'Could not update .env'}</p>}
    </div>
  )
}

export function FyersLoginDialog() {
  const { fyersLogin, setFyersLogin } = useUi()
  const { data: s } = useStatus()
  const login = useFyersLogin()
  const complete = useFyersComplete()
  const toast = useToast()
  const [phase, setPhase] = useState<Phase>('idle')
  const [session, setSession] = useState<FyersLoginResponse | null>(null)
  const [pasted, setPasted] = useState('')
  const tokenBefore = useRef<string | null>(null)
  const wait = useFyersWait(fyersLogin && phase === 'waiting')
  const f = s?.fyers

  const close = () => {
    setFyersLogin(false); setPhase('idle'); setSession(null); setPasted(''); login.reset(); complete.reset()
  }
  const loggedIn = (name: string | null, note?: string) => {
    toast({ tone: 'good', title: `Logged in to Fyers${name ? ` as ${name}` : ''}`, detail: note || 'Scans now use Fyers real-time prices.' })
    close()
  }

  // the Fyers tab finished the login (the callback saved a new token): this dialog's work is done
  useEffect(() => {
    const w = wait.data
    if (phase === 'waiting' && w?.logged_in_today && w.token_created && w.token_created !== tokenBefore.current) {
      complete.reset()
      loggedIn(w.user_name, w.note)
    }
  }, [wait.data, phase]) // eslint-disable-line react-hooks/exhaustive-deps

  const start = () => {
    tokenBefore.current = f?.token_created ?? null
    // opened inside the click, so no pop-up blocker stops it; pointed at Fyers once the server made the link
    const tab = window.open('about:blank', '_blank')
    if (tab) tab.opener = null
    login.mutate('direct', {
      onSuccess: (r) => {
        setSession(r)
        if (r.login_url) {
          if (tab) tab.location.href = r.login_url
          else window.open(r.login_url, '_blank', 'noopener')
        }
        setPhase(r.mode === 'direct' ? 'waiting' : 'paste')
      },
      onError: () => tab?.close(),
    })
  }

  const finish = () =>
    complete.mutate(pasted.trim(), {
      onSuccess: (r) => {
        if (r.ok) loggedIn(r.user_name, r.status?.note)
        else {
          // the server already used up the pending login: start again
          toast({ tone: 'bad', title: 'Fyers did not confirm the login', detail: 'Start the login again; if it keeps failing, check FYERS_CLIENT_ID and the secret in .env.' })
          setPhase('idle'); setSession(null); setPasted('')
        }
      },
    })

  const err = login.error ?? complete.error
  const oneClick = f?.direct_mode === 'app' || f?.direct_mode === 'listener'
  return (
    <Dialog
      open={fyersLogin}
      onClose={close}
      title="Log in to Fyers"
      footer={
        phase === 'paste' ? (
          <>
            <Button variant="ghost" onClick={close}>Cancel</Button>
            <Button variant="primary" disabled={!pasted.trim()} loading={complete.isPending} onClick={finish}>Complete login</Button>
          </>
        ) : (
          <Button variant="ghost" onClick={close}>{phase === 'waiting' ? 'Cancel' : 'Close'}</Button>
        )
      }
    >
      <div className="space-y-4 text-[13px]">
        {f && (
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 rounded-lg border border-line bg-raised/50 p-3 text-xs">
            <span className="text-muted">App credentials</span><span className="text-right">{f.configured ? `configured (${f.client_id_masked ?? 'hidden'})` : 'missing in .env'}</span>
            <span className="text-muted">Today's login</span><span className={f.logged_in_today ? 'text-right text-profit' : 'text-right text-warn'}>{f.logged_in_today ? `yes${f.user_name ? ` (${f.user_name})` : ''}` : 'no'}</span>
            <span className="text-muted">Login</span><span className="text-right">{oneClick ? 'one click' : 'one click + paste (setup below)'}</span>
          </div>
        )}
        {err && (
          <Banner tone="danger">
            <div className="font-medium">{isFailure(err) ? err.message : 'Login failed'}</div>
            {isFailure(err) && err.hint && <div className="text-xs text-muted">{err.hint}</div>}
          </Banner>
        )}

        {phase === 'idle' && (
          <>
            <p className="text-muted">
              Fyers asks for a new login every morning (after 6 AM). With it, scans use real-time Fyers prices instead of Yahoo (~15 min delayed), and you can import your holdings.
            </p>
            <Button variant="primary" size="md" icon={<LogIn className="h-4 w-4" />} loading={login.isPending} disabled={f ? !f.configured : false} onClick={start}>
              Log in with Fyers
            </Button>
            <p className="text-xs text-faint">
              {oneClick
                ? 'Fyers opens in a new tab. Log in there with your Fyers ID, PIN and TOTP; this window updates by itself.'
                : 'Fyers opens in a new tab. After you log in there, copy the address bar back here (or do the one-time setup below to skip that).'}
            </p>
            {f && !f.configured && <p className="text-xs text-warn">Add FYERS_CLIENT_ID and FYERS_SECRET_KEY to the .env file next to config.yaml (see README), then restart Quant Desk.</p>}
            {f && f.configured && !oneClick && <DirectSetup f={f} />}
          </>
        )}

        {phase === 'waiting' && (
          <div className="space-y-3">
            <div className="flex items-center gap-2.5 rounded-lg border border-line p-3">
              <Spinner className="h-4 w-4" />
              <div>
                <div className="font-medium">Waiting for you to log in on the Fyers tab…</div>
                <div className="text-xs text-muted">This window closes by itself when Fyers sends you back. The link works for 10 minutes.</div>
              </div>
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
              {session?.login_url && (
                <a href={session.login_url} target="_blank" rel="noopener noreferrer" className="link inline-flex items-center gap-1">Open the Fyers page again <ExternalLink className="h-3 w-3" /></a>
              )}
              <button type="button" className="link" onClick={() => setPhase('paste')}>It didn't come back? Paste the address instead</button>
            </div>
          </div>
        )}

        {phase === 'paste' && (
          <>
            {session && <ol className="list-decimal space-y-1 pl-5 text-muted">{session.instructions.map((i) => <li key={i}>{i}</li>)}</ol>}
            {session?.login_url && (
              <a href={session.login_url} target="_blank" rel="noopener noreferrer" className="link inline-flex items-center gap-1 text-xs">
                Open the Fyers login page again <ExternalLink className="h-3 w-3" />
              </a>
            )}
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-muted">Paste the full address from the browser bar after logging in</span>
              <textarea value={pasted} onChange={(e) => setPasted(e.target.value)} rows={3} spellCheck={false} className="input h-auto w-full py-2 font-mono text-xs" placeholder="http://127.0.0.1:8000/…?s=ok&code=200&auth_code=…&state=…" />
            </label>
          </>
        )}
      </div>
    </Dialog>
  )
}
