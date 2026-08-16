# MT5 Signal Relay API Documentation

**Version:** 1.0  
**Last Updated:** 2026-08-17  
**Base URL:** `https://hirmes.bensserver.cloud/api`

---

## 🔐 Authentication

All protected endpoints require one of the following:

### Header Authentication
```http
Authorization: Bearer <SECRET>
X-Signal-Secret: <SECRET>
```

### Query Parameter
```
GET /api/health?secret=<SECRET>
```

**Secret Key:** `3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610`

---

## 📡 Endpoints

### 1. GET `/api/health`

Check system health and active positions status.

**Request:**
```http
GET https://hirmes.bensserver.cloud/api/health?secret=3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610
```

**Response (Success - 200):**
```json
{
  "status": "ok",
  "timestamp": "2026-08-17T01:58:43.499851+07:00",
  "stats": {
    "queued_selfbot": 0,
    "pending_orders": 0,
    "active_locks": 1
  },
  "active_locks": {
    "BTCUSD": {
      "position": 1289819334,
      "ts": 1786906682.4773424,
      "price": 63142.352,
      "waiting_sltp": true
    }
  }
}
```

**Fields:**
- `status`: `"ok"` | `"error"`
- `timestamp`: ISO 8601 format
- `stats`: System statistics (queue counts)
- `active_locks`: Object with currently locked symbols and their position details

---

### 2. GET `/api/positions`

List all active trading positions.

**Request:**
```http
GET https://hirmes.bensserver.cloud/api/positions?secret=3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610
```

**Response (Success - 200):**
```json
{
  "count": 1,
  "data": [
    {
      "symbol": "BTCUSD",
      "position_id": 1289819334,
      "price": 63142.352,
      "opened_at": 1786906682.4773424,
      "status": "active"
    }
  ]
}
```

**Fields:**
- `count`: Number of active positions
- `data[]`: Array of position objects
  - `symbol`: Trading pair (e.g., BTCUSD, XAUUSD)
  - `position_id`: Unique position identifier from MT5
  - `price`: Entry price
  - `opened_at`: Unix timestamp when position opened
  - `status`: `"active"`

---

### 3. GET `/api/logs`

Recent activity logs for monitoring and debugging.

**Request:**
```http
GET https://hirmes.bensserver.cloud/api/logs?secret=3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610
```

**Response (Success - 200):**
```json
{
  "count": 100,
  "data": [
    "[08-17 01:48:45] 📤 ENTRY sent immediately: BUY BTCUSD @ 63144.32 (SLTP pending)",
    "[08-17 01:49:06] 📤 SLTP sent separately: BTCUSD SL=62899.797 TP=63378.81",
    "[08-17 01:50:15] 🔓 CLOSE #BTCUSD pos 1289819334 — lock dilepas"
  ]
}
```

**Fields:**
- `count`: Total log entries available
- `data[]`: Array of log messages (last 100)

---

### 4. GET `/api/config/detector`

Retrieve detector configuration (for editing in web dashboard).

**Request:**
```http
GET https://hirmes.bensserver.cloud/api/config/detector?mask=1&secret=3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610
```

**Query Parameters:**
- `mask=1` (optional): Mask password (show as `**********`)
- `mask=0` or omitted: Show password in plain text (not recommended)

**Response (Success - 200):**
```json
{
  "mt5": {
    "login": 49781717,
    "password": "**********",
    "server": "HFMarketsGlobal-Demo",
    "terminal_path": "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
  },
  "receiver_url": "https://hirmes.bensserver.cloud/api/signal",
  "secret": "3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610",
  "settings": {
    "poll_interval": 1.0,
    "health_interval": 60,
    "startup_seed_minutes": 5,
    "notify_restart": true
  }
}
```

**Fields:**
- `mt5`: MT5 connection settings
  - `login`: Account number
  - `password`: Password (masked if requested)
  - `server`: Broker server name
  - `terminal_path`: Path to MT5 executable on RDP
- `receiver_url`: VPS receiver URL
- `secret`: Signal secret token
- `settings`: Operational parameters
  - `poll_interval`: Trade detection frequency (seconds)
  - `health_interval`: Health check frequency (seconds)
  - `startup_seed_minutes`: Delay before processing deals after startup
  - `notify_restart`: Enable/disable restart notifications

---

### 5. PUT `/api/config/detector`

Update detector configuration.

**Request:**
```http
PUT https://hirmes.bensserver.cloud/api/config/detector?secret=3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610
Content-Type: application/json

{
  "mt5": {
    "login": 98765432,
    "password": "new_password_here",
    "server": "Broker-Live"
  },
  "settings": {
    "poll_interval": 0.5,
    "health_interval": 120
  }
}
```

**Request Body Fields:**
- `mt5` (object): Update any or all MT5 credentials
- `settings` (object): Update operational parameters

**Response (Success - 200):**
```json
{
  "status": "updated",
  "version": 15,
  "checksum": "abc123def456"
}
```

**Response Fields:**
- `status`: `"updated"` | `"error"`
- `version`: New config version number (increments on each update)
- `checksum`: SHA256 checksum of updated config (useful for auto-refresh UI)

**Error Response (400):**
```json
{
  "error": "missing mt5.login"
}
```

---

### 6. GET `/api/config/detector/checksum`

Lightweight endpoint for checking if config has changed (auto-refresh trigger).

**Request:**
```http
GET https://hirmes.bensserver.cloud/api/config/detector/checksum?secret=3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610
```

**Response (Success - 200):**
```json
{
  "version": 1,
  "checksum": "fa5ab48f7a94063a"
}
```

**Usage:** Compare returned checksum/version with previous request to determine if UI needs refresh.

---

### 7. POST `/api/reset`

Force reset entire system state (clear all locks/pending orders).

**Request:**
```http
POST https://hirmes.bensserver.cloud/api/reset?secret=3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610
```

**Response (Success - 200):**
```json
{
  "status": "reset complete"
}
```

⚠️ **Warning:** This will clear ALL active positions locks and pending orders. Use with caution!

---

## 🧪 Example API Calls

### cURL Examples

```bash
# Get health status
curl "https://hirmes.bensserver.cloud/api/health?secret=3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610"

# Get active positions
curl "https://hirmes.bensserver.cloud/api/positions?secret=3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610"

# Update detector config
curl -X PUT "https://hirmes.bensserver.cloud/api/config/detector?secret=3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610" \
  -H "Content-Type: application/json" \
  -d '{
    "mt5": {
      "login": 98765432,
      "server": "Broker-Live"
    },
    "settings": {
      "poll_interval": 0.5
    }
  }'

# Reset system
curl -X POST "https://hirmes.bensserver.cloud/api/reset?secret=3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610"
```

### JavaScript Fetch Examples

```javascript
const SECRET = '3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610';
const BASE = 'https://hirmes.bensserver.cloud/api';

// Get health
async function getHealth() {
  const res = await fetch(`${BASE}/health?secret=${SECRET}`);
  return res.json();
}

// Get positions
async function getPositions() {
  const res = await fetch(`${BASE}/positions?secret=${SECRET}`);
  return res.json();
}

// Update config
async function updateConfig(mt5, settings) {
  const res = await fetch(`${BASE}/config/detector?secret=${SECRET}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mt5, settings }),
  });
  return res.json();
}

// Reset system
async function resetSystem() {
  const res = await fetch(`${BASE}/reset?secret=${SECRET}`, {
    method: 'POST',
  });
  return res.json();
}
```

---

## 🎨 React Dashboard Component Example

Here's a complete working component you can use directly:

```jsx
// components/SMT5Dashboard.jsx
import { useState, useEffect } from 'react';

const SECRET = '3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610';
const BASE = 'https://hirmes.bensserver.cloud/api';

export default function MT5SignalDashboard() {
  const [health, setHealth] = useState(null);
  const [positions, setPositions] = useState([]);
  const [logs, setLogs] = useState([]);
  const [config, setConfig] = useState(null);
  const [isSaving, setIsSaving] = useState(false);

  // Fetch all data
  async function fetchData() {
    try {
      const [healthRes, posRes, logsRes, cfgRes] = await Promise.all([
        fetch(`${BASE}/health?secret=${SECRET}`),
        fetch(`${BASE}/positions?secret=${SECRET}`),
        fetch(`${BASE}/logs?secret=${SECRET}`),
        fetch(`${BASE}/config/detector?mask=1&secret=${SECRET}`),
      ]);

      setHealth(await healthRes.json());
      setPositions((await posRes.json()).data || []);
      setLogs((await logsRes.json()).data || []);
      setConfig(await cfgRes.json());
    } catch (err) {
      console.error('API Error:', err);
    }
  }

  // Auto-refresh every 5 seconds
  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  // Handle config update
  async function saveConfig() {
    if (!config) return;
    
    setIsSaving(true);
    try {
      const res = await fetch(`${BASE}/config/detector?secret=${SECRET}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mt5: config.mt5,
          settings: config.settings,
        }),
      });
      
      if (res.ok) {
        alert('✅ Configuration saved successfully!');
        fetchData();
      } else {
        const error = await res.json();
        alert(`❌ Failed: ${error.error}`);
      }
    } catch (err) {
      console.error('Save Error:', err);
      alert('❌ Network error');
    } finally {
      setIsSaving(false);
    }
  }

  // Reset system
  async function handleReset() {
    if (!confirm('⚠️ This will clear ALL active positions and locks.\n\nAre you sure?')) return;
    
    try {
      const res = await fetch(`${BASE}/reset?secret=${SECRET}`, { method: 'POST' });
      const result = await res.json();
      
      if (result.status === 'reset complete') {
        alert('✅ System reset complete!');
        fetchData();
      } else {
        alert('❌ Reset failed');
      }
    } catch (err) {
      alert('❌ Reset failed: ' + err.message);
    }
  }

  // Format timestamp
  const formatDate = (unix) => {
    return new Date(unix * 1000).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="bg-white rounded-xl shadow-md p-6 mb-6">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">
            🚀 MT5 Signal Relay Dashboard
          </h1>
          <p className="text-gray-600">Real-time signal monitoring and configuration</p>
        </div>

        {/* Health Status */}
        {health && (
          <div className={`bg-${health.status === 'ok' ? 'green' : 'red'}-50 border border-${health.status === 'ok' ? 'green' : 'red'}-200 rounded-xl p-4 mb-6 flex items-center justify-between`}>
            <div className="flex items-center">
              <span className={`w-3 h-3 rounded-full mr-3 ${health.status === 'ok' ? 'bg-green-500' : 'bg-red-500'}`}></span>
              <span className="text-lg font-semibold">
                {health.status.toUpperCase()} SYSTEM
              </span>
            </div>
            <span className="text-gray-700">{health.timestamp}</span>
          </div>
        )}

        {/* Active Positions Table */}
        <div className="bg-white rounded-xl shadow-md p-6 mb-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
            <span className="mr-2">📊</span>
            Active Positions ({positions.length})
          </h2>
          
          {positions.length === 0 ? (
            <p className="text-gray-500 italic text-center py-8">No active positions</p>
          ) : (
            <table className="w-full border-collapse">
              <thead>
                <tr className="bg-gray-100 border-b">
                  <th className="text-left py-3 px-4 text-sm font-semibold text-gray-700">Symbol</th>
                  <th className="text-left py-3 px-4 text-sm font-semibold text-gray-700">Price</th>
                  <th className="text-left py-3 px-4 text-sm font-semibold text-gray-700">Opened At</th>
                  <th className="text-left py-3 px-4 text-sm font-semibold text-gray-700">Status</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos, idx) => (
                  <tr key={idx} className="border-b hover:bg-gray-50">
                    <td className="py-3 px-4 text-gray-900 font-medium">{pos.symbol}</td>
                    <td className="py-3 px-4">${pos.price.toFixed(3)}</td>
                    <td className="py-3 px-4 text-gray-600">{formatDate(pos.opened_at)}</td>
                    <td className="py-3 px-4">
                      <span className="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded-full">
                        {pos.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Recent Activity Logs */}
        <div className="bg-white rounded-xl shadow-md p-6 mb-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
            <span className="mr-2">📋</span>
            Recent Activity (last 20)
          </h2>
          <ul className="bg-gray-50 rounded-lg p-4 h-64 overflow-y-auto text-sm space-y-2">
            {logs.slice(-20).map((log, idx) => (
              <li key={idx} className="font-mono text-gray-700">
                {log.replace(/\uD83D[\uDC00-\uDFFF]/g, '').replace(/./g, '')}
              </li>
            ))}
          </ul>
        </div>

        {/* Config Editor */}
        {config && (
          <div className="bg-white rounded-xl shadow-md p-6">
            <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
              <span className="mr-2">⚙️</span>
              Detector Configuration
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* MT5 Settings */}
              <div>
                <h3 className="text-lg font-semibold text-gray-700 mb-3 pb-2 border-b">MT5 Connection</h3>
                
                <label className="block mb-4">
                  <label className="text-sm text-gray-700 font-medium block mb-1">MT5 Login</label>
                  <input
                    type="number"
                    value={config.mt5.login || ''}
                    onChange={(e) => {
                      const newCfg = { ...config };
                      newCfg.mt5.login = parseInt(e.target.value) || 0;
                      setConfig(newCfg);
                    }}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                </label>

                <label className="block mb-4">
                  <label className="text-sm text-gray-700 font-medium block mb-1">Server</label>
                  <input
                    type="text"
                    value={config.mt5.server || ''}
                    onChange={(e) => {
                      const newCfg = { ...config };
                      newCfg.mt5.server = e.target.value;
                      setConfig(newCfg);
                    }}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                </label>

                <label className="block">
                  <label className="text-sm text-gray-700 font-medium block mb-1">Password (masked)</label>
                  <input
                    type="password"
                    disabled
                    value={config.mt5.password || '****'}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-gray-100 cursor-not-allowed"
                  />
                  <p className="text-xs text-gray-500 mt-1">Password masked for security</p>
                </label>
              </div>

              {/* Settings */}
              <div>
                <h3 className="text-lg font-semibold text-gray-700 mb-3 pb-2 border-b">Operational Settings</h3>
                
                <label className="block mb-4">
                  <label className="text-sm text-gray-700 font-medium block mb-1">Poll Interval (seconds)</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0.1"
                    max="10"
                    value={config.settings.poll_interval || 1.0}
                    onChange={(e) => {
                      const newCfg = { ...config };
                      newCfg.settings.poll_interval = parseFloat(e.target.value) || 1.0;
                      setConfig(newCfg);
                    }}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <p className="text-xs text-gray-500 mt-1">Trade detection frequency</p>
                </label>

                <label className="block mb-4">
                  <label className="text-sm text-gray-700 font-medium block mb-1">Health Check Interval (seconds)</label>
                  <input
                    type="number"
                    step="1"
                    min="10"
                    max="300"
                    value={config.settings.health_interval || 60}
                    onChange={(e) => {
                      const newCfg = { ...config };
                      newCfg.settings.health_interval = parseInt(e.target.value) || 60;
                      setConfig(newCfg);
                    }}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <p className="text-xs text-gray-500 mt-1">System health monitoring frequency</p>
                </label>

                <label className="block">
                  <label className="text-sm text-gray-700 font-medium block mb-1">Startup Seed Minutes</label>
                  <input
                    type="number"
                    step="1"
                    min="0"
                    max="60"
                    value={config.settings.startup_seed_minutes || 5}
                    onChange={(e) => {
                      const newCfg = { ...config };
                      newCfg.settings.startup_seed_minutes = parseInt(e.target.value) || 0;
                      setConfig(newCfg);
                    }}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <p className="text-xs text-gray-500 mt-1">Delay before processing old trades after startup</p>
                </label>
              </div>
            </div>

            {/* Action Buttons */}
            <div className="flex gap-4 mt-6 pt-4 border-t">
              <button
                onClick={saveConfig}
                disabled={isSaving}
                className="flex-1 bg-blue-600 hover:bg-blue-700 text-white font-semibold py-3 px-6 rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center"
              >
                {isSaving ? (
                  <>
                    <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    Saving...
                  </>
                ) : (
                  '💾 Save Configuration'
                )}
              </button>
              
              <button
                onClick={handleReset}
                className="flex-1 bg-red-600 hover:bg-red-700 text-white font-semibold py-3 px-6 rounded-lg transition-all flex items-center justify-center"
              >
                🔴 Reset System
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

---

## 🎯 Quick Start Guide

### For Frontend Developers

1. **Authentication**: Include `secret` in all requests (query param or header)
2. **Auto-refresh**: Poll `/api/health`, `/api/positions`, `/api/logs` every 5-10 seconds
3. **Config Management**: Use `/api/config/detector` endpoints for read/write
4. **Error Handling**: All errors return JSON with `error` field
5. **Rate Limiting**: None - all requests authenticated with secret

### Common Patterns

```javascript
// Real-time monitoring
setInterval(async () => {
  const health = await getHealth();
  if (health.status !== 'ok') {
    showErrorToast('System unhealthy');
  }
}, 5000);

// Position tracking
const watchPositions = async () => {
  const positions = await getPositions();
  updateUI(positions.data);
};

// Config editing workflow
const handleEditConfig = async (formValues) => {
  try {
    await putConfig(formValues);
    refetch();
  } catch (err) {
    showNotification(err.response?.data?.error, 'error');
  }
};
```

---

## 📝 Additional Notes

- All timestamps are in **UTC+7 (WIB)** timezone
- Password is **never editable via API** (security)
- `detector_config.json` lives on **VPS** only
- RDP detector pulls config every **30 seconds** automatically
- All signals go through Telegram selfbot with custom emojis
- No rate limiting - assume infinite concurrent connections acceptable

---

## 🆘 Troubleshooting

### "unauthorized" error
→ Verify secret key is correct: `3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610`

### "no pending entry" on SLTP
→ Entry was already sent, SLTP arrived too late or without proper match

### Suppressed signals
→ Symbol already has active position lock (prevent duplicate entries)

### Timeout errors
→ Increase request timeout to 30 seconds minimum

---

**Ready to build! 🚀**