# Quant Desk UI

The browser app for the NSE stock scanner: React 18 + TypeScript + Vite, TanStack Query/Table,
lightweight-charts 5 and Tailwind. FastAPI (`web/api`) serves the built app from `web/ui/dist` at
http://127.0.0.1:8600, on the same origin as `/api`.

Specs: `docs/ui_spec.md`, with `docs/ui_spec_review.md` overriding it where they differ.

## Everyday use

Run `3_dashboard.bat` in the app folder. It builds the UI the first time (needs Node.js once) and starts the server.

After changing anything under `web/ui/src`, rebuild so the server picks it up:

```bat
cd web\ui
npm run build
```

Never edit `dist/` by hand: it is build output.

## Development

```bat
cd web\ui
npm ci
npm run dev        :: http://127.0.0.1:5173, /api forwarded to the API on :8600 (QD_API=... to change)
npm test           :: vitest (formatting, sizing, chart mappers)
npm run lint
```

## Layout

| Path | What it holds |
| --- | --- |
| `src/api/types.ts` | The API contract (keep in sync with `web/api/models`) |
| `src/api/client.ts` | `fetchJson` + one typed call per endpoint; errors become `ApiFailure` (`OFFLINE` drives the "can't reach the server" banner) |
| `src/api/hooks.ts` | TanStack Query hooks. Scan data never goes stale on a timer: the shell invalidates it when `/api/status` reports a new scan. |
| `src/app/` | Router, app shell (rail, top bar, banners, shortcuts), UI state |
| `src/components/` | Primitives (`ui.tsx`), tables, charts, domain widgets |
| `src/pages/` | One file per route |
| `src/lib/` | Formatting (Indian grouping, IST), sizing mirror, chart theme, storage helpers |

## Rules the code follows

- Times are IST (Asia/Kolkata); money uses Indian grouping (₹1,23,456).
- Server text (intraday rules and summary, SEBI facts, notes, warnings) is shown as sent, never hard-coded.
- Every non-GET request sends `X-Quant-Desk: 1` (the server's CSRF guard).
- The app never places orders. Orders are shown for the user to place in Fyers.
