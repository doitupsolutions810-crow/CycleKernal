#!/usr/bin/env bash
# Probe compose services. Exit 1 if any required probe fails.
set -u

fail=0
report() {
  local name="$1" ok="$2" detail="$3"
  if [ "$ok" = "1" ]; then
    echo "OK   $name  $detail"
  else
    echo "FAIL $name  $detail"
    fail=1
  fi
}

probe_http() {
  local name="$1" url="$2"
  if ! command -v curl >/dev/null 2>&1; then
    report "$name" 0 "curl missing"
    return
  fi
  local code
  code=$(curl -fsS -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || true)
  if [ "$code" = "200" ] || [ "$code" = "204" ] || [ "$code" = "302" ]; then
    report "$name" 1 "$url -> $code"
  else
    report "$name" 0 "$url -> ${code:-unreachable}"
  fi
}

probe_http simulation "http://127.0.0.1:5000/health"
probe_http monitoring "http://127.0.0.1:3000/health"
probe_http prometheus "http://127.0.0.1:9090/-/ready"
probe_http grafana "http://127.0.0.1:3001/api/health"
probe_http frontend "http://127.0.0.1:8080/"

if command -v redis-cli >/dev/null 2>&1; then
  if redis-cli -h 127.0.0.1 ping 2>/dev/null | grep -q PONG; then
    report redis 1 "PING"
  else
    report redis 0 "PING failed"
  fi
else
  report redis 0 "redis-cli missing or port 6379 closed"
fi

if command -v nc >/dev/null 2>&1 && nc -z 127.0.0.1 27017 >/dev/null 2>&1; then
  report mongodb 1 "tcp 27017 open"
else
  report mongodb 0 "tcp 27017 closed"
fi

if ! command -v docker >/dev/null 2>&1; then
  report docker 0 "docker CLI not installed; make up cannot start the stack"
fi

exit "$fail"
