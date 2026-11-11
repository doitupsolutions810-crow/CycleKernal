#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE=${1:-"$ROOT/.env"}
[ -r "$ENV_FILE" ] || { echo "Cannot read env file: $ENV_FILE" >&2; exit 2; }

# Convert ignored local env values to JSON and stream directly to kubectl stdin.
# Secret data never appears in command-line arguments or printed output.
python3 - "$ENV_FILE" <<'PY' | kubectl apply -f -
import base64, json, pathlib, sys
values = {}
for line in pathlib.Path(sys.argv[1]).read_text().splitlines():
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    key, value = line.split('=', 1)
    values[key] = value
required = ('MONGO_INITDB_ROOT_PASSWORD', 'GRAFANA_ADMIN_PASSWORD')
missing = [key for key in required if not values.get(key)]
if missing:
    raise SystemExit('Missing required secret keys: ' + ', '.join(missing))
secret = {
    'apiVersion': 'v1',
    'kind': 'Secret',
    'metadata': {'name': 'cyclekernel-secrets', 'namespace': 'cyclekernel'},
    'type': 'Opaque',
    'data': {
        'MONGO_INITDB_ROOT_USERNAME': base64.b64encode(b'cyclekernel').decode(),
        'MONGO_INITDB_ROOT_PASSWORD': base64.b64encode(values['MONGO_INITDB_ROOT_PASSWORD'].encode()).decode(),
        'GRAFANA_ADMIN_PASSWORD': base64.b64encode(values['GRAFANA_ADMIN_PASSWORD'].encode()).decode(),
        'LLM_BASE_URL': base64.b64encode(values.get('LLM_BASE_URL', '').encode()).decode(),
        'LLM_API_KEY': base64.b64encode(values.get('LLM_API_KEY', '').encode()).decode(),
        'LLM_MODEL': base64.b64encode(values.get('LLM_MODEL', 'gpt-4o-mini').encode()).decode(),
    },
}
print(json.dumps(secret))
PY
kubectl apply -f "$ROOT/k8s/cyclekernel.yaml"
