# Prompt untuk Build Dashboard Frontend (Copy-Paste Ready)

```markdown
Build complete web dashboard untuk Signal Relay System (MT5 → Telegram). Backend API udah ada di `http://localhost:8080`.

## Tech Stack
- Next.js 14 App Router (TypeScript)
- Tailwind CSS + shadcn/ui
- TanStack Query untuk data fetching
- Lucide React icons

## API Endpoints (all at localhost:8080)
- GET `/api/health` - system status
- GET `/api/positions` - active positions list
- GET `/api/logs?limit=50` - recent logs
- POST `/api/reset` - reset system (needs auth via ?secret=TOKEN or Authorization header)
- POST `/api/signal` - send EA signals (auth required)

Secret token: read from `.env RECEIVER_SECRET` file on server

## Project Structure Required
src/
├── app/
│   ├── layout.tsx       # dark theme, provider wrappers
│   ├── page.tsx         # main dashboard
│   ├── api/             # client-side API handlers
│   │   └── client.ts    # all fetch functions
│   ├── components/      # UI components
│   │   ├── health-card.tsx
│   │   ├── positions-table.tsx
│   │   ├── logs-panel.tsx
│   │   └── actions-bar.tsx
│   └── lib/
│       └── utils.ts     # formatting helpers

## Features to Build

### 1. Main Dashboard (page.tsx)
- Layout grid dengan cards: Health Status, Active Positions, System Logs
- Auto-refresh setiap 5 detik
- Manual refresh button per card
- Loading skeletons & error boundaries

### 2. Health Card Component
- Live status indicator (green pulse animation when ok)
- Stats display: active positions count, pending orders, locked symbols
- Last update timestamp

### 3. Positions Table
- Show: Symbol | Position ID | Price | Opened At
- Sort by column click
- Click position ID → copy to clipboard
- Format price with Indonesia locale (63.070, not 63070)
- Timestamp formatted: "16 Agu 2026 20:30"

### 4. Logs Panel
- Last 100 entries scrollable container
- Copy entire logs button
- Filter by keyword search
- Export to CSV option

### 5. Actions Bar
- Reset system button (with confirmation modal)
- Manual test signal form (input slots untuk test OPEN command)
- Secret key input field (for API calls)

## Requirements
- Dark mode default (#1a1a2e background)
- Responsive design (mobile down to 375px)
- Accessible (WCAG AA minimum)
- Error handling for all API calls
- Use React Query cache with 5s staleTime

## Deliverables
Return complete codebase as single response with:
1. Full file tree structure
2. Complete TypeScript code for each file
3. package.json with dependencies
4. README.md with setup instructions (`pnpm install`, `pnpm dev`)

Do NOT include documentation files in output—just build the frontend code that uses the existing backend API.
```
