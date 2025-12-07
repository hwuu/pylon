#!/bin/bash
set -e

case "$1" in
  serve)
    shift
    exec python -m pylon serve "$@"
    ;;

  mock)
    exec python -m tests.mock_server.app
    ;;

  frontend)
    # Generate config.js from environment variable
    export API_BASE_URL="${API_BASE_URL:-http://localhost:8001}"
    envsubst < /app/frontend/dist/config.template.js > /app/frontend/dist/config.js

    # Start nginx in foreground
    exec nginx -g "daemon off;"
    ;;

  hash-password)
    exec python -m pylon hash-password
    ;;

  *)
    # Pass through any other command
    exec "$@"
    ;;
esac
