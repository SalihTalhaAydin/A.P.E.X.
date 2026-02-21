#!/usr/bin/env bash
# Encrypt .env into .env.encrypted (safe to commit to git)
# Usage: bash scripts/encrypt-env.sh

set -e
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
ENC_FILE="$REPO_ROOT/.env.encrypted"
VERSION_FILE="$REPO_ROOT/.openssl-version"

# ── Load pinned OpenSSL version ──────────────────────────────────────
if [ ! -f "$VERSION_FILE" ]; then
  echo "ERROR: $VERSION_FILE not found. Cannot verify OpenSSL version."
  exit 1
fi
# shellcheck source=../.openssl-version
source "$VERSION_FILE"

# ── Verify installed OpenSSL matches pinned major version ────────────
INSTALLED_VERSION="$(openssl version 2>/dev/null)" || {
  echo "ERROR: openssl not found in PATH."
  exit 1
}
INSTALLED_MAJOR="$(echo "$INSTALLED_VERSION" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 | cut -d. -f1)"
INSTALLED_MINOR="$(echo "$INSTALLED_VERSION" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 | cut -d. -f2)"

if [ "$INSTALLED_MAJOR" != "$OPENSSL_MAJOR" ]; then
  echo "ERROR: OpenSSL major version mismatch."
  echo "  Required: ${OPENSSL_MAJOR}.${OPENSSL_MINOR}.x (from .openssl-version)"
  echo "  Installed: $INSTALLED_VERSION"
  echo "Install OpenSSL ${OPENSSL_MAJOR}.x to continue."
  exit 1
fi

if [ "$INSTALLED_MINOR" -lt "$OPENSSL_MINOR" ]; then
  echo "WARNING: OpenSSL minor version is older than pinned."
  echo "  Required: >= ${OPENSSL_MAJOR}.${OPENSSL_MINOR}.x (from .openssl-version)"
  echo "  Installed: $INSTALLED_VERSION"
  echo "Proceeding, but consider upgrading."
fi

# ── Encrypt ──────────────────────────────────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found."
  exit 1
fi

echo "Encrypting .env → .env.encrypted"
echo "  OpenSSL: $INSTALLED_VERSION"
echo "  Cipher:  aes-256-cbc  |  KDF: pbkdf2  |  Iterations: $OPENSSL_PBKDF2_ITER"
echo "Enter a password (you'll need this to decrypt later):"
openssl enc -aes-256-cbc -salt -pbkdf2 -iter "$OPENSSL_PBKDF2_ITER" \
  -in "$ENV_FILE" -out "$ENC_FILE"
echo "Done! .env.encrypted is ready to commit."
