#!/usr/bin/env bash
# ============================================================
# MT5 SIGNAL — SETUP & CEK MULTI AKUN (multi MT5 + multi channel)
# Jalankan di VPS: bash setup.sh
#
# Yang dikerjain:
#   1. Cek service receiver + selfbot hidup
#   2. Cek telegram_config.json: route PROD / TEST / VIP ada apa belum
#      → VIP belum ada? langsung ditanya chat_id + bisa langsung diset
#   3. Cek detector config per akun (public + vip) di VPS
#   4. Cetak panduan path persis buat RDP Windows (1 detector / 2 detector)
#
# Path RDP (jawaban "pake 2 path nya mana aja"):
#   Script     : C:\mt5-signal\signal_detector.py   (SATU script buat semua akun)
#   Akun Publik: C:\mt5-signal\config.json          (source: "")
#   Akun VIP   : C:\mt5-signal\config_vip.json      (source: "vip")
#   Jalankan 2 : python signal_detector.py --config config_vip.json
#                (atau dobel-klik run_vip.bat)
# ============================================================
set -u
BASE="$(cd "$(dirname "$0")" && pwd)"
RECEIVER="$BASE/receiver.py"
TGCFG="$BASE/telegram_config.json"
ENVF="$BASE/.env"
FAIL=0

say()  { printf '%s\n' "$*"; }
ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✘\033[0m %s\n' "$*"; FAIL=1; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
ask()  { printf '\033[36m%s\033[0m' "$*"; }

SECRET=""
[ -f "$ENVF" ] && SECRET="$(grep '^RECEIVER_SECRET=' "$ENVF" | cut -d= -f2-)"

say ""
say "============================================="
say " MT5 SIGNAL — SETUP MULTI AKUN"
say " Base: $BASE"
say "============================================="

# ---------- 1. Service ----------
say ""
say "[1/4] Service systemd"
for svc in mt5-signal-receiver mt5-signal-selfbot; do
  if systemctl is-active --quiet "$svc"; then ok "$svc active"; else bad "$svc TIDAK active — sudo systemctl restart $svc"; fi
done

# ---------- 2. Config channel ----------
say ""
say "[2/4] Config channel (telegram_config.json)"

json_get() { python3 -c "
import json,sys
try:
    c=json.load(open('$TGCFG'))
except Exception:
    print(''); sys.exit(0)
key='$1'
for r in c.get('routes',[]):
    if r.get('name')==key or (key=='test' and r.get('test')):
        print(r.get('chat_id','')); break
"; }

if [ ! -f "$TGCFG" ]; then
  warn "telegram_config.json belum ada — receiver pakai fallback (PROD/TEST hardcode, VIP gak bisa)"
else
  ok "file ada"
fi

PROD_ID="$(json_get prod)"
TEST_ID="$(json_get test)"
VIP_ID="$(json_get vip)"

if [ -n "$PROD_ID" ]; then ok "route PROD : $PROD_ID"; else warn "route PROD : belum di-set (fallback channel default selfbot: -1001816822545)"; fi
if [ -n "$TEST_ID" ]; then ok "route TEST : $TEST_ID"; else warn "route TEST : belum di-set (fallback: -1004479253024)"; fi

SETUP_VIP=0
if [ -n "$VIP_ID" ]; then
  ok "route VIP  : $VIP_ID"
else
  bad "route VIP  : BELUM ADA — sinyal source 'vip' bakal DIBUANG (anti-bocor)"
  SETUP_VIP=1
fi

# ---------- 3. Setup VIP kalau belum ----------
if [ "$SETUP_VIP" = "1" ] && [ -n "$SECRET" ]; then
  say ""
  ask "Mau set channel VIP sekarang? Tempel chat_id VIP (kosong = skip): "
  read -r VIP_INPUT
  if [ -n "$VIP_INPUT" ]; then
    case "$VIP_INPUT" in
      -100*|-*) ;;
      *) warn "chat_id biasanya mulai -100... — tetap dipakai apa adanya" ;;
    esac
    say ""
    ask "Nama route VIP [vip]: "
    read -r VIP_NAME
    VIP_NAME="${VIP_NAME:-vip}"
    python3 - "$TGCFG" "$VIP_NAME" "$VIP_INPUT" <<'PYEOF'
import json, sys, os
path, name, chat = sys.argv[1], sys.argv[2], int(sys.argv[3])
try:
    cfg = json.load(open(path))
except Exception:
    cfg = {"accounts": [], "routes": []}
routes = [r for r in cfg.get("routes", []) if r.get("name") != name and not r.get("test")]
routes.append({"name": name, "chat_id": chat, "source": name, "enabled": True})
if not any(r.get("test") for r in routes):
    routes.append({"name": "test", "chat_id": -1004479253024, "test": True, "enabled": True})
cfg["routes"] = routes
cfg["meta"] = cfg.get("meta", {})
cfg["meta"]["version"] = int(cfg["meta"].get("version", 0)) + 1
cfg["meta"]["updated_at"] = __import__("time").time()
tmp = path + ".tmp"
json.dump(cfg, open(tmp, "w"), indent=2)
os.replace(tmp, path)
print("saved")
PYEOF
    if [ -f "$TGCFG" ]; then
      ok "route '$VIP_NAME' (source: $VIP_NAME) tersimpan → selfbot hot-reload ≤5s"
      VIP_ID="$VIP_INPUT"
      SETUP_VIP=0
    else
      bad "gagal nulis $TGCFG"
    fi
  else
    warn "di-skip — jalankan ulang setup.sh kapan aja buat set VIP"
  fi
fi
[ -n "$SECRET" ] || warn ".env / RECEIVER_SECRET gak ketemu — setup VIP via API dilewati (bisa manual: POST /api/config/telegram)"

# ---------- 4. Detector config ----------
say ""
say "[3/4] Detector config per akun (di VPS, dikelola via API)"
for SRC in public vip; do
  F="$BASE/detector_config.json"
  [ "$SRC" != "public" ] && F="$BASE/detector_config_${SRC}.json"
  if [ -f "$F" ]; then
    V="$(python3 -c "import json;print(json.load(open('$F')).get('meta',{}).get('version',0))" 2>/dev/null || echo 0)"
    ok "source=$SRC → $(basename "$F") (v$V)"
  elif [ "$SRC" = "public" ]; then
    warn "source=public → detector_config.json belum ada (opsional; detector pakai config lokal RDP)"
  else
    warn "source=vip → detector_config_vip.json belum ada (opsional; VIP detector pakai config lokal sampai diset via API)"
  fi
done

# ---------- 5. Panduan RDP ----------
say ""
say "[4/4] Setup di RDP Windows"
say "  Copy 2 file ini ke RDP (mis. C:\\mt5-signal\\):"
say "    - receiver/src/signal_detector.py   (script-nya, SATU untuk semua akun)"
say "    - receiver/src/config.example.json  (template)"
say ""
say "  AKUN PUBLIK (sudah jalan, gak perlu diubah):"
say "    config : C:\\mt5-signal\\config.json            → \"source\": \"\""
say "    jalan  : python signal_detector.py"
say ""
if [ "$SETUP_VIP" = "0" ] && [ -n "$VIP_ID" ]; then
  ok "Route VIP aktif ($VIP_ID) — detector VIP langsung bisa nyambung"
else
  warn "Route VIP belum aktif — set dulu di atas, baru detector VIP nyambung"
fi
say "  AKUN VIP:"
say "    config : C:\\mt5-signal\\config_vip.json        → \"source\": \"vip\""
say "             (login/password/server = akun MT5 VIP, secret sama)"
say "    jalan  : python signal_detector.py --config config_vip.json"
say "             (atau dobel-klik scripts\\run_vip.bat)"
say ""
say "  File per instance (otomatis, gak tabrakan):"
say "    publik : detector.log / detector_state.json / health.json / config_checksums.json"
say "    vip    : detector_vip.log / detector_state_vip.json / health_vip.json / config_checksums_vip.json"

say ""
[ "$FAIL" = "0" ] && say "SEMUa CEK LOLOS ✅" || say "ADA YANG PERLU DIBENERIN (lihat ✘ di atas)"
exit $FAIL
