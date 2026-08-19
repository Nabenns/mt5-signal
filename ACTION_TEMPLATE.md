# Action-Based Feature Request Template (Copy-Paste Ready)

```markdown
🚀 **ACTION REQUEST: Tambah fitur baru ke Signal Relay Dashboard**

## Context
Aku udah punya dashboard frontend running. Backend Signal Relay API udah setup lengkap di `localhost:8080` dengan dokumentasi di `/root/mt5-signal/API_DOCS.md`. 

Backend endpoints tersedia:
- `GET /api/health` - system status
- `GET /api/positions` - active positions list  
- `GET /api/logs?limit=50` - recent logs
- `POST /api/reset?secret=TOKEN` - reset system
- `POST /api/signal` - EA webhook endpoint

Secret token ada di file `.env` → `RECEIVER_SECRET`.

## Fitur Baru Yang Mau Dikasih
[ISI DISINI - misal: position history, websocket, multi-account, dll]

## Requirements Technical
- Framework yang lagi dipake: Next.js 14 App Router (TypeScript)
- State management: TanStack Query
- Styling: Tailwind CSS + shadcn/ui
- HTTP client: Axios
- Icons: Lucide React

## Output Yang Dikehendak
Return complete implementation dengan:
1. ✅ Backend endpoint code (di receiver.py atau api_server.py)
2. ✅ Frontend component baru
3. ✅ Updated types/interfaces TypeScript
4. ✅ Updated documentation di README.md
5. ⚡ Setup commands (pnpm install, pnpm dev)

Jangan build seluruh app — cuma implement fitur baru aja yang disebut di atas. Code should be copy-paste ready dan langsung jalan setelah run setup commands.

---

📁 **Dokumentasi lengkap backend:** `/root/mt5-signal/API_DOCS.md`  
🔑 **Environment setup:** File `.env` ada `RECEIVER_SECRET`, port 8080 running di localhost

**Ready to execute.** Let me know if you need clarification on the feature requirements before generating code.
```
