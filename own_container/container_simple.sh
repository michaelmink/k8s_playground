#!/usr/bin/env bash
# container_simple.sh
# ===================
# Ein Container in Bash - jeder Syscall ist ein eigener Schritt.
# Das Skript ruft sich selbst rekursiv auf, wobei jeder exec-Aufruf
# genau einen Namespace-Syscall macht.
#
# Verwendung:  sudo bash container_simple.sh ./rootfs

set -e
SELF="$(realpath "$0")"
ROOTFS="${1:-./rootfs}"
STEP="${2:-1}"

case "$STEP" in
  1)
    echo "=== Schritt 1: UTS-Namespace anlegen ==="
    # Syscall: unshare(2) mit CLONE_NEWUTS → eigener Hostname
    exec unshare --uts bash "$SELF" "$ROOTFS" 2
    ;;

  2)
    echo "=== Schritt 2: Hostname setzen ==="
    # Syscall: sethostname(2) - nur sichtbar im UTS-Namespace
    hostname container
    exec bash "$SELF" "$ROOTFS" 3
    ;;

  3)
    echo "=== Schritt 3: Mount-Namespace anlegen ==="
    # Syscall: unshare(2) mit CLONE_NEWNS → eigene Mount-Tabelle
    exec unshare --mount bash "$SELF" "$ROOTFS" 4
    ;;

  4)
    echo "=== Schritt 4: PID-Namespace anlegen ==="
    # Syscall: unshare(2) mit CLONE_NEWPID → eigene Prozesstabelle
    # --fork nötig: PID-NS gilt erst für Kindprozesse
    exec unshare --pid --fork bash "$SELF" "$ROOTFS" 5
    ;;

  5)
    echo "=== Schritt 5: In das rootfs wechseln ==="
    # Syscall: chdir(2)
    cd "$ROOTFS"

    echo "=== Schritt 6: Mount-Tabelle privat machen ==="
    # Syscall: mount(2) mit MS_REC|MS_PRIVATE
    # Verhindert, dass spätere Mounts auf den Host durchschlagen
    mount --make-rprivate /

    echo "=== Schritt 7: /proc einhängen ==="
    # Syscall: mount(2) Typ "proc" - nötig für ps, top etc.
    mount -t proc proc proc/

    echo "=== Schritt 8: Shell im Container starten ==="
    # Syscall: chroot(2) - setzt / auf unser rootfs
    # Syscall: execve(2) - ersetzt diesen Prozess durch /bin/sh
    echo "Du bist jetzt im Container. Probiere: hostname, ps aux, ls /"
    exec chroot . /bin/sh
    ;;
esac
