#!/usr/bin/env bash
# Decrypt .env.encrypted back into .env
# Usage: bash scripts/decrypt-env.sh

set -e
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
ENC_FILE="$REPO_ROOT/.env.encrypted"

if [ ! -f "$ENC_FILE" ]; then
  echo "ERROR: $ENC_FILE not found. Nothing to decrypt."
  exit 1
fi

if [ -f "$ENV_FILE" ]; then
  read -rp ".env already exists. Overwrite? (y/N): " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
  fi
fi

echo "Decrypting .env.encrypted → .env"
openssl enc -aes-256-cbc -d -salt -pbkdf2 -in "$ENC_FILE" -out "$ENV_FILE"
echo "Done! .env restored."
