#!/usr/bin/env bash
#
# Outside monitor for adelia.godi.ai (audit 2.9).
#
# On 2026-08-31 the box was down for 2 h 14 min and nobody noticed: the
# outage was found by accident, while checking something else. A monitor
# that runs ON the server cannot report that the server is gone, so this
# one is meant to run somewhere else (the Mac, a phone, a VPS) and speaks
# through the Telegram bot Santiago already reads.
#
# It alerts on the SECOND consecutive failure, not the first: a single
# timeout on a home connection is noise, two in a row is an outage. It
# alerts once more on recovery, with how long it lasted, and stays quiet
# in between. Silence means healthy.
#
# Install (macOS, every 5 minutes):
#   cp scripts/com.godi.adelia-monitor.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/com.godi.adelia-monitor.plist
# Install (Linux, cron):
#   */5 * * * * /opt/adelia/scripts/monitor-adelia.sh >/dev/null 2>&1
#
# Credentials: ~/.config/godi/telegram.env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
set -uo pipefail

BASE="${ADELIA_BASE_URL:-https://adelia.godi.ai}"
ENV_FILE="${GODI_TELEGRAM_ENV:-$HOME/.config/godi/telegram.env}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/adelia-monitor"
STATE="${STATE_DIR}/state"          # ok | fail1 | alerted
SINCE="${STATE_DIR}/down_since"     # epoch of the first failed check
TIMEOUT="${ADELIA_MONITOR_TIMEOUT:-15}"

mkdir -p "${STATE_DIR}"
[[ -r "${ENV_FILE}" ]] && . "${ENV_FILE}"

notify() {
  local text="$1"
  if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
    printf 'monitor: %s (sin credenciales de Telegram)\n' "${text}" >&2
    return
  fi
  curl -s -m 20 -o /dev/null \
    -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${text}" \
    --data-urlencode "disable_web_page_preview=true" || true
}

# Two probes, because they fail for different reasons: /healthz dies when the
# API or the database is gone (and 200 there means the DB answered), /es dies
# when the web container or the tunnel is gone.
probe() {
  local url="$1" body code
  body=$(curl -s -m "${TIMEOUT}" -w '\n%{http_code}' "${url}" 2>/dev/null) || return 1
  code=$(printf '%s' "${body}" | tail -1)
  [[ "${code}" == "200" ]] || return 1
  # /healthz reports its own degradation with a 200 only when every check is ok
  [[ "${url}" == *"/healthz" ]] && { printf '%s' "${body}" | grep -q '"status":"ok"' || return 1; }
  return 0
}

failed=""
probe "${BASE}/healthz" || failed="healthz"
probe "${BASE}/es" || failed="${failed:+${failed} y }web"

prev=$(cat "${STATE}" 2>/dev/null || echo ok)
now=$(date +%s)

if [[ -n "${failed}" ]]; then
  case "${prev}" in
    ok)
      echo fail1 > "${STATE}"; echo "${now}" > "${SINCE}" ;;      # esperar confirmación
    fail1)
      echo alerted > "${STATE}"
      notify "🔴 AdelIA caída: falla ${failed} en ${BASE} (dos comprobaciones seguidas, $(date '+%H:%M'))." ;;
    alerted) : ;;                                                  # ya avisado, silencio
  esac
  exit 1
fi

if [[ "${prev}" == "alerted" ]]; then
  since=$(cat "${SINCE}" 2>/dev/null || echo "${now}")
  mins=$(( (now - since) / 60 ))
  notify "🟢 AdelIA recuperada tras ${mins} min ($(date '+%H:%M'))."
fi
echo ok > "${STATE}"
rm -f "${SINCE}"
exit 0
