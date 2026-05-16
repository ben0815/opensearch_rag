#!/bin/bash
set -e

# Load overrides from the mounted secrets file (passwords, API keys, etc.)
# These values take precedence over the env vars already set by Docker Compose.
if [ -f "/app/secrets/.env" ] && [ -s "/app/secrets/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source /app/secrets/.env
    set +a
fi

# Execute the main command
exec python -m "$@"
