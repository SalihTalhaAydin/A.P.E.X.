#!/usr/bin/env bash
# Encrypt .env into .env.encrypted (safe to commit to git)
# Usage: bash scripts/encrypt-env.sh

set -e
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
ENC_FILE="$REPO_ROOT/.env.encrypted"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found."
  exit 1
fi

echo "Encrypting .env → .env.encrypted"
echo "Enter a password (you'll need this to decrypt later):"
openssl enc -aes-256-cbc -salt -pbkdf2 -in "$ENV_FILE" -out "$ENC_FILE"
echo "Done! .env.encrypted is ready to commit."
