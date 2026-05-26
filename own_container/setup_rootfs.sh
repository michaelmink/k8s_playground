#!/usr/bin/env bash
# setup_rootfs.sh
# ===============
# Lädt ein minimales Alpine Linux Root-Dateisystem herunter und entpackt es.
# Dieses Verzeichnis wird als "Container-Image" für own_container.py verwendet.
#
# Verwendung:
#   bash setup_rootfs.sh            # Alpine 3.20 (Standard)
#   bash setup_rootfs.sh 3.19       # bestimmte Alpine-Version

set -euo pipefail

VERSION="${1:-3.20}"
ARCH="x86_64"
ROOTFS_DIR="$(dirname "$0")/rootfs"
TARBALL="alpine-minirootfs-${VERSION}.0-${ARCH}.tar.gz"
URL="https://dl-cdn.alpinelinux.org/alpine/v${VERSION}/releases/${ARCH}/${TARBALL}"

echo "═══════════════════════════════════════════════════════════"
echo "  Alpine Linux ${VERSION} rootfs herunterladen"
echo "═══════════════════════════════════════════════════════════"
echo "  Quelle: ${URL}"
echo "  Ziel:   ${ROOTFS_DIR}/"
echo ""

if [[ -d "${ROOTFS_DIR}" && -f "${ROOTFS_DIR}/bin/sh" ]]; then
    echo "  rootfs existiert bereits. Überspringen."
    echo "  (Löschen und neu anlegen: rm -rf ${ROOTFS_DIR} && bash setup_rootfs.sh)"
    exit 0
fi

mkdir -p "${ROOTFS_DIR}"

echo "  Lade herunter..."
if command -v curl &>/dev/null; then
    curl -L --progress-bar "${URL}" -o "/tmp/${TARBALL}"
elif command -v wget &>/dev/null; then
    wget -q --show-progress "${URL}" -O "/tmp/${TARBALL}"
else
    echo "Fehler: curl oder wget wird benötigt." >&2
    exit 1
fi

echo "  Entpacke..."
tar -xzf "/tmp/${TARBALL}" -C "${ROOTFS_DIR}"
rm "/tmp/${TARBALL}"

echo ""
echo "  Fertig! rootfs liegt in: ${ROOTFS_DIR}/"
echo ""
echo "  Jetzt starten:"
echo "    sudo python3 own_container.py run ./rootfs /bin/sh"
echo ""

# Zeige was im rootfs liegt
echo "  Inhalt des rootfs:"
ls "${ROOTFS_DIR}/"
