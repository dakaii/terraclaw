#!/usr/bin/env bash
# Apply Terraclaw infrastructure. Configure gcp:project first (see README).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec pulumi up "$@"
