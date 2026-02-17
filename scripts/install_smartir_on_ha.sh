#!/bin/sh
# Install SmartIR into Home Assistant (run from HA Terminal add-on or SSH)
# Usage: Run this on your HA host. Config dir is usually /config.

set -e
CONFIG_DIR="${CONFIG_DIR:-/config}"
COMPONENT_DIR="$CONFIG_DIR/custom_components"
SMARTIR_DIR="$COMPONENT_DIR/smartir"
# 1.17.12 = HA 2024.10+. Use 1.18.1 if you're on HA 2025.5+
RELEASE_URL="https://github.com/smartHomeHub/SmartIR/archive/refs/tags/1.17.12.tar.gz"

echo "Installing SmartIR into $COMPONENT_DIR ..."
mkdir -p "$COMPONENT_DIR"
cd /tmp
curl -sSL "$RELEASE_URL" -o smartir.tar.gz
tar xzf smartir.tar.gz
rm -rf "$SMARTIR_DIR"
mv SmartIR-1.17.12/custom_components/smartir "$COMPONENT_DIR/"
rm -rf SmartIR-1.17.12 smartir.tar.gz
echo "Done! SmartIR installed to $SMARTIR_DIR"
echo ""
echo "Next:"
echo "  1. Add 'smartir:' to configuration.yaml (or add via UI)"
echo "  2. Restart Home Assistant"
echo "  3. Settings -> Devices -> Add Integration -> SmartIR"
