#!/usr/bin/env bash
set -euo pipefail

APP_URL="${APP_URL:-http://127.0.0.1:8089/}"
APP_PORT="${APP_PORT:-8089}"
PID_FILE="${WSL_PID_FILE:-/tmp/event_radar_8089.pid}"
LOG_FILE="${WSL_LOG_FILE:-/tmp/event_radar_8089.log}"
SETUP_LOG="${WSL_SETUP_LOG:-/tmp/event_radar_setup.log}"
ATTACH_TO_CONSOLE="${EVENT_RADAR_ATTACH_TO_CONSOLE:-0}"

service_pid=""
cleanup_running=0

health_ok() {
  curl -fsS "${APP_URL}healthz" >/dev/null 2>&1
}

root_ok() {
  curl -fsS "${APP_URL}" >/dev/null 2>&1
}

listener_pid() {
  ss -ltnp "( sport = :${APP_PORT} )" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -n 1
}

pid_command() {
  local pid="$1"
  ps -p "${pid}" -o command= 2>/dev/null || true
}

is_event_radar_pid() {
  local pid="$1"
  local command
  command="$(pid_command "${pid}")"
  [[ "${command}" == *"event_radar.main:app"* ]] || [[ "${command}" == *"event-radar"* ]]
}

is_windows_tool_path() {
  local candidate="$1"
  [[ "${candidate}" == /mnt/* ]] || [[ "${candidate}" == *.exe ]] || [[ "${candidate}" == *.cmd ]] || [[ "${candidate}" == *.bat ]]
}

pick_linux_tool() {
  local tool_name="$1"
  local candidate=""
  while IFS= read -r candidate; do
    [[ -n "${candidate}" ]] || continue
    [[ -x "${candidate}" ]] || continue
    if ! is_windows_tool_path "${candidate}"; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done < <(which -a "${tool_name}" 2>/dev/null | awk '!seen[$0]++')

  local nvm_dir="${NVM_DIR:-$HOME/.nvm}"
  while IFS= read -r candidate; do
    [[ -n "${candidate}" ]] || continue
    [[ -x "${candidate}" ]] || continue
    if ! is_windows_tool_path "${candidate}"; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done < <(find "${nvm_dir}/versions/node" -type f -path "*/bin/${tool_name}" 2>/dev/null | sort -V -r)

  return 1
}

ensure_frontend_toolchain() {
  local node_bin npm_bin
  node_bin="$(pick_linux_tool node)" || {
    echo "No Linux node binary found in WSL PATH or NVM." >>"${SETUP_LOG}"
    return 1
  }
  npm_bin="$(pick_linux_tool npm)" || {
    echo "No Linux npm binary found in WSL PATH or NVM." >>"${SETUP_LOG}"
    return 1
  }

  export PATH="$(dirname "${node_bin}"):${PATH}"
  export EVENT_RADAR_NODE_BIN="${node_bin}"
  export EVENT_RADAR_NPM_BIN="${npm_bin}"

  {
    echo "Using node: ${EVENT_RADAR_NODE_BIN}"
    echo "Using npm: ${EVENT_RADAR_NPM_BIN}"
  } >>"${SETUP_LOG}"
}

stop_pid() {
  local pid="$1"
  if [[ -z "${pid}" ]]; then
    return 0
  fi

  if ! is_event_radar_pid "${pid}"; then
    return 1
  fi

  if kill -0 "${pid}" 2>/dev/null; then
    kill "${pid}" 2>/dev/null || true
    for _ in $(seq 1 30); do
      if ! kill -0 "${pid}" 2>/dev/null; then
        return 0
      fi
      sleep 0.2
    done
    kill -9 "${pid}" 2>/dev/null || true
  fi
}

cleanup_service() {
  local exit_code="${1:-0}"
  if [[ "${cleanup_running}" -eq 1 ]]; then
    return
  fi
  cleanup_running=1

  if [[ -n "${service_pid}" ]]; then
    stop_pid "${service_pid}" || true
  fi
  rm -f "${PID_FILE}"
}

on_exit() {
  cleanup_service "$?"
}

on_signal() {
  trap - EXIT HUP INT TERM
  cleanup_service 0
  exit 0
}

wait_for_attached_service() {
  local wait_status=0
  wait "${service_pid}" || wait_status=$?
  service_pid=""
  rm -f "${PID_FILE}"
  return "${wait_status}"
}

ensure_python_env() {
  if [[ ! -d .venv ]]; then
    python3 -m venv .venv >"${SETUP_LOG}" 2>&1
  fi

  # Sync editable install when the environment is first created or pyproject changed.
  if [[ ! -f .venv/.event_radar_python_ready ]] || [[ pyproject.toml -nt .venv/.event_radar_python_ready ]]; then
    . .venv/bin/activate
    pip install -e .[dev] >>"${SETUP_LOG}" 2>&1
    touch .venv/.event_radar_python_ready
  else
    . .venv/bin/activate
  fi
}

ensure_frontend_assets() {
  ensure_frontend_toolchain

  if [[ ! -d frontend/node_modules ]] || [[ frontend/package-lock.json -nt frontend/node_modules ]]; then
    (
      cd frontend
      "${EVENT_RADAR_NPM_BIN}" install >>"${SETUP_LOG}" 2>&1
    )
  fi

  if [[ ! -f event_radar/static/app/index.html ]] \
    || find frontend/src frontend/public -type f -newer event_radar/static/app/index.html | grep -q . \
    || [[ frontend/package.json -nt event_radar/static/app/index.html ]] \
    || [[ frontend/package-lock.json -nt event_radar/static/app/index.html ]] \
    || [[ frontend/vite.config.ts -nt event_radar/static/app/index.html ]]; then
    (
      cd frontend
      "${EVENT_RADAR_NPM_BIN}" run build >>"${SETUP_LOG}" 2>&1
    )
  fi
}

if [[ "${ATTACH_TO_CONSOLE}" != "1" ]] && health_ok && root_ok; then
  exit 0
fi

existing_pid="$(listener_pid)"
if [[ -n "${existing_pid}" ]]; then
  if is_event_radar_pid "${existing_pid}"; then
    stop_pid "${existing_pid}"
  else
    echo "Port ${APP_PORT} is already in use by a non-Event Radar process (${existing_pid}): $(pid_command "${existing_pid}")" >&2
    exit 1
  fi
fi

if [[ -f "${PID_FILE}" ]]; then
  file_pid="$(tr -d '[:space:]' <"${PID_FILE}")"
  if [[ -n "${file_pid}" ]]; then
    if is_event_radar_pid "${file_pid}"; then
      stop_pid "${file_pid}"
    fi
  fi
  rm -f "${PID_FILE}"
fi

: >"${SETUP_LOG}"
echo "Event Radar startup began at $(date --iso-8601=seconds)" >>"${SETUP_LOG}"

ensure_python_env
ensure_frontend_assets

if [[ "${ATTACH_TO_CONSOLE}" == "1" ]]; then
  trap on_exit EXIT
  trap on_signal HUP INT TERM
  .venv/bin/python -m uvicorn event_radar.main:app --host 127.0.0.1 --port "${APP_PORT}" >"${LOG_FILE}" 2>&1 &
else
  nohup .venv/bin/python -m uvicorn event_radar.main:app --host 127.0.0.1 --port "${APP_PORT}" >"${LOG_FILE}" 2>&1 < /dev/null &
fi
service_pid="$!"
echo "${service_pid}" >"${PID_FILE}"

sleep 3

health_ok
root_ok

if [[ "${ATTACH_TO_CONSOLE}" == "1" ]]; then
  if [[ -t 1 ]] && command -v clear >/dev/null 2>&1; then
    clear
  fi
  echo "Event Radar started successfully."
  echo
  echo "${APP_URL}"
  echo
  echo "Close this window to stop Event Radar."
  echo
  echo "WSL logs:"
  echo "  ${LOG_FILE}"
  echo "  ${SETUP_LOG}"
  echo
  wait_for_attached_service
fi
