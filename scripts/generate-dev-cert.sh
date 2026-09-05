#!/usr/bin/env bash
set -euo pipefail

# Prevents Git Bash (MSYS) on Windows from rewriting -subj's leading "/" into
# a Windows path. No effect on Linux/macOS.
export MSYS_NO_PATHCONV=1

cd "$(dirname "$0")/.."

CERT_DIR="infra/nginx/certs"
mkdir -p "$CERT_DIR"

openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout "$CERT_DIR/dev.key" \
  -out "$CERT_DIR/dev.crt" \
  -days 365 \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

echo "Generated $CERT_DIR/dev.crt and $CERT_DIR/dev.key (365 days, self-signed, dev only)."
