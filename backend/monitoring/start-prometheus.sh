#!/bin/sh
set -eu
# Prometheus does not expand environment variables in authorization settings.
# Keep the token out of command arguments and the checked-in configuration.
umask 077
printf '%s' "${METRICS_BEARER_TOKEN:-}" > /tmp/metrics-token
exec /bin/prometheus "$@"
