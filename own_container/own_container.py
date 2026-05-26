#!/usr/bin/env python3
"""
own_container.py
================
Ein minimaler Container-Runtime in ~300 Zeilen Python.
Zeigt was Docker wirklich unter der Haube macht.

Konzepte (in Reihenfolge der Ausführung):
  1. cgroups v2        – Ressourcen-Limits (Memory, CPU)
  2. Linux Namespaces  – Isolation: UTS (Hostname), PID, Mount, IPC
  3. pivot_root        – Dateisystem-Isolation (sicherer als chroot)
  4. /proc mounten     – eigene Prozesssicht im Container

Verwendung:
  sudo python3 own_container.py run ./rootfs /bin/sh
  sudo python3 own_container.py run ./rootfs /bin/echo Hallo
  sudo python3 own_container.py run --mem=128 --hostname=mybox ./rootfs /bin/sh

Vorbereitung:
  bash setup_rootfs.sh   # lädt Alpine Linux rootfs herunter
"""

import os
import sys
import ctypes
import ctypes.util
import signal


# ══════════════════════════════════════════════════════════════════════════════
# SCHRITT 1 – Linux-Syscall-Wrapper via ctypes
#
# Python hat keine direkte API für diese Low-Level-Syscalls.
# Wir rufen sie direkt aus libc auf – genau wie C-Programme.
# ══════════════════════════════════════════════════════════════════════════════

libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)

# ── Namespace-Flags (aus linux/sched.h) ───────────────────────────────────────
# Diese Flags steuern, welche Kernel-Ressourcen isoliert werden.
CLONE_NEWNS   = 0x00020000  # Mount Namespace  – eigene Sicht auf Dateisysteme
CLONE_NEWUTS  = 0x04000000  # UTS Namespace    – eigener Hostname & Domainname
CLONE_NEWIPC  = 0x08000000  # IPC Namespace    – eigene Message Queues / Semaphoren
CLONE_NEWPID  = 0x20000000  # PID Namespace    – PID 1 im Container, isolierte Prozesstabelle
CLONE_NEWNET  = 0x40000000  # Network Namespace – eigene Netzwerkinterfaces (hier nicht genutzt)

# ── Mount-Flags (aus sys/mount.h) ─────────────────────────────────────────────
MS_NOSUID  = 2
MS_NODEV   = 4
MS_NOEXEC  = 8
MS_BIND    = 4096
MS_REC     = 16384
MS_PRIVATE = 1 << 18

MNT_DETACH = 2  # für umount2: Aushängen ohne Warten auf Prozesse


def _syscall_check(ret: int, name: str) -> None:
    """Prüft den Rückgabewert eines Syscalls. Wirft bei Fehler eine OSError."""
    if ret != 0:
        err = ctypes.get_errno()
        raise OSError(err, f"{name}: {os.strerror(err)}")


def unshare(flags: int) -> None:
    """
    Erstellt neue Namespaces für den aktuellen Prozess.
    Entspricht dem CLI-Tool 'unshare(1)'.

    WICHTIG bei CLONE_NEWPID: Der aufrufende Prozess bleibt im ALTEN
    PID-Namespace! Erst seine KINDER landen im neuen. Deshalb brauchen
    wir danach os.fork().
    """
    _syscall_check(libc.unshare(ctypes.c_int(flags)), "unshare")


def sethostname(name: str) -> None:
    """Setzt den Hostname im UTS-Namespace (nur sichtbar innerhalb des Containers)."""
    b = name.encode()
    _syscall_check(libc.sethostname(b, ctypes.c_size_t(len(b))), "sethostname")


def mount(source: str | None, target: str, fstype: str | None,
          flags: int = 0, data: str | None = None) -> None:
    """
    Hängt ein Dateisystem ein.

    Beispiele:
      mount("proc",   "/proc", "proc")          # /proc für Prozesstabelle
      mount("/pfad",  "/pfad", "",   MS_BIND)   # Bind-Mount (Verzeichnis einspiegeln)
      mount("",       "/",     "",   MS_PRIVATE) # Host-Mounts vom Container trennen
    """
    ret = libc.mount(
        source.encode() if source else None,
        target.encode(),
        fstype.encode() if fstype else None,
        ctypes.c_ulong(flags),
        data.encode() if data else None,
    )
    _syscall_check(ret, f"mount({source!r} → {target!r}, flags={flags:#x})")


def umount2(target: str, flags: int = 0) -> None:
    """Hängt ein Dateisystem aus. Mit MNT_DETACH sofort, auch wenn noch Prozesse drauf sind."""
    _syscall_check(libc.umount2(target.encode(), ctypes.c_int(flags)), f"umount2({target!r})")


def pivot_root(new_root: str, put_old: str) -> None:
    """
    Tauscht den Root-Dateisystem-Pointer des Prozesses aus.

    pivot_root ist SICHERER als chroot():
      - chroot: nur ein Pfad-Präfix-Trick, der Kernel-Zugriff bleibt
      - pivot_root: echter Tausch des Namespace-Root, alter Root wird ausgehängt

    SYS_pivot_root = 155 (x86_64 Linux)
    """
    ret = libc.syscall(ctypes.c_long(155), new_root.encode(), put_old.encode())
    _syscall_check(ret, f"pivot_root({new_root!r}, {put_old!r})")


# ══════════════════════════════════════════════════════════════════════════════
# SCHRITT 2 – cgroups v2: Ressourcen-Limits
#
# cgroups (Control Groups) sind der Kernel-Mechanismus hinter
# "docker run --memory=256m --cpus=0.5".
# In cgroup v2 gibt es eine einheitliche Hierarchie unter /sys/fs/cgroup/.
# ══════════════════════════════════════════════════════════════════════════════

CGROUP_ROOT = "/sys/fs/cgroup"


def setup_cgroup(name: str, mem_limit_mb: int, cpu_weight: int) -> str:
    """
    Erstellt eine cgroup für den Container und setzt Limits.

    Ablauf:
      1. Verzeichnis anlegen: /sys/fs/cgroup/<name>/
      2. Controller im Eltern-cgroup aktivieren (subtree_control)
      3. Limits in die Controller-Dateien schreiben
      4. Eigene PID in cgroup.procs eintragen → gilt für alle Kinder

    Gibt den cgroup-Pfad zurück.
    """
    cg_path = f"{CGROUP_ROOT}/{name}"
    os.makedirs(cg_path, exist_ok=True)

    # Controller in der Eltern-cgroup freischalten (damit Kinder sie nutzen können)
    try:
        with open(f"{CGROUP_ROOT}/cgroup.subtree_control", "w") as f:
            f.write("+memory +cpu")
    except (PermissionError, OSError) as e:
        print(f"  [cgroup] subtree_control nicht setzbar: {e}")

    # Memory Limit: Container bekommt maximal mem_limit_mb MB
    try:
        with open(f"{cg_path}/memory.max", "w") as f:
            f.write(str(mem_limit_mb * 1024 * 1024))
        # Swap deaktivieren (Container soll nicht in Swap ausweichen)
        with open(f"{cg_path}/memory.swap.max", "w") as f:
            f.write("0")
        print(f"  [cgroup] memory.max = {mem_limit_mb} MB")
    except (PermissionError, FileNotFoundError) as e:
        print(f"  [cgroup] Memory-Limit nicht setzbar: {e}")

    # CPU Weight: steuert relative CPU-Zuteilung (Standard = 100, Bereich 1–10000)
    try:
        with open(f"{cg_path}/cpu.weight", "w") as f:
            f.write(str(cpu_weight))
        print(f"  [cgroup] cpu.weight = {cpu_weight}")
    except (PermissionError, FileNotFoundError) as e:
        print(f"  [cgroup] CPU-Weight nicht setzbar: {e}")

    # Aktuellen Prozess in die cgroup eintragen.
    # Alle forked Kinder erben die cgroup automatisch!
    with open(f"{cg_path}/cgroup.procs", "w") as f:
        f.write(str(os.getpid()))

    return cg_path


def cleanup_cgroup(cg_path: str) -> None:
    """Löscht die cgroup nach Beendigung des Containers."""
    import time
    time.sleep(0.2)  # kurz warten bis alle Prozesse beendet sind
    try:
        os.rmdir(cg_path)
    except OSError:
        pass  # ignorieren, wenn noch Prozesse drin sind


# ══════════════════════════════════════════════════════════════════════════════
# SCHRITT 3 – Dateisystem-Isolation mit pivot_root
#
# Docker-Images sind Union-Filesystems (OverlayFS), hier nutzen wir ein
# simples tar-entpacktes Alpine Linux als "Image".
# pivot_root macht das Verzeichnis zum echten "/" des Containers.
# ══════════════════════════════════════════════════════════════════════════════

def setup_rootfs(new_root: str) -> None:
    """
    Isoliert das Dateisystem des Container-Prozesses via pivot_root.

    Schritt für Schritt:
      1. Mount-Propagation vom Host trennen (MS_PRIVATE):
         Neue Mounts im Container soll der Host nicht sehen.

      2. rootfs als Bind-Mount einhängen:
         pivot_root verlangt, dass new_root selbst ein Mount-Point ist.

      3. pivot_root ausführen:
         - new_root wird das neue "/"
         - Das alte "/" landet temporär in "/.put_old"

      4. /proc einhängen:
         Ohne /proc gibt es kein 'ps', kein /proc/self, kein 'top'.

      5. Alten Root aushängen:
         Damit der Container keinen Zugriff auf den Host hat.
    """
    # (1) Alle Mounts des aktuellen Namespace auf "private" setzen
    mount("", "/", "", MS_REC | MS_PRIVATE)

    # (2) rootfs als Bind-Mount (notwendig für pivot_root)
    mount(new_root, new_root, "", MS_BIND | MS_REC)

    # Verzeichnis für den alten Root anlegen
    put_old = os.path.join(new_root, ".put_old")
    os.makedirs(put_old, exist_ok=True)

    # (3) pivot_root: new_root wird "/", alter Root → "/.put_old"
    pivot_root(new_root, put_old)
    os.chdir("/")
    print(f"  [rootfs] pivot_root ausgeführt – neues '/' ist das Container-Rootfs")

    # (4) /proc mounten – brauchen wir für ps, top, /proc/self/...
    os.makedirs("/proc", exist_ok=True)
    mount("proc", "/proc", "proc", MS_NOSUID | MS_NODEV | MS_NOEXEC)
    print(f"  [rootfs] /proc eingehängt")

    # /sys optional (für sysinfo, uname etc.)
    os.makedirs("/sys", exist_ok=True)
    try:
        mount("sysfs", "/sys", "sysfs", MS_NOSUID | MS_NODEV | MS_NOEXEC)
    except OSError:
        pass

    # /dev/pts für Terminal-Pseudoterminals (z.B. für 'sh')
    os.makedirs("/dev/pts", exist_ok=True)
    try:
        mount("devpts", "/dev/pts", "devpts")
    except OSError:
        pass

    # (5) Alten Root aushängen (MNT_DETACH = lazy unmount)
    try:
        umount2("/.put_old", MNT_DETACH)
        os.rmdir("/.put_old")
        print(f"  [rootfs] Alter Host-Root ausgehängt – Isolation vollständig")
    except OSError as e:
        print(f"  [rootfs] Warnung beim Aushängen des alten Root: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# SCHRITT 4 – Container-Prozess (Kind-Prozess in den neuen Namespaces)
# ══════════════════════════════════════════════════════════════════════════════

def child_main(rootfs: str, hostname: str, command: list[str]) -> None:
    """
    Dieser Code läuft INNERHALB der neuen Namespaces.

    Nach os.fork() ist dieser Prozess PID 1 im neuen PID-Namespace –
    genau wie 'init' oder 'systemd' auf einem echten System.
    Wenn PID 1 stirbt, beendet der Kernel alle anderen Prozesse im Namespace.
    """
    print(f"\n── Container-Prozess gestartet ──────────────────────────────────")
    print(f"  [container] PID im neuen Namespace: {os.getpid()}  (sollte 1 sein)")

    # UTS-Namespace: eigenen Hostname setzen
    sethostname(hostname)
    print(f"  [container] Hostname gesetzt: '{hostname}'")

    # Dateisystem-Isolation
    setup_rootfs(rootfs)

    # Umgebungsvariablen für den Container-Prozess
    env = {
        "PATH":      "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "TERM":      os.environ.get("TERM", "xterm"),
        "HOME":      "/root",
        "CONTAINER": "own_container",
    }

    print(f"  [container] Starte Befehl: {' '.join(command)}")
    print(f"─────────────────────────────────────────────────────────────────\n")

    # execvpe ersetzt den aktuellen Prozess durch den gewünschten Befehl.
    # Ab hier läuft NUR noch der angegebene Befehl – kein Python mehr.
    try:
        os.execvpe(command[0], command, env)
    except FileNotFoundError:
        print(f"Fehler: '{command[0]}' nicht im rootfs gefunden.", file=sys.stderr)
        sys.exit(127)


# ══════════════════════════════════════════════════════════════════════════════
# SCHRITT 5 – Haupt-Funktion: alles zusammenfügen
# ══════════════════════════════════════════════════════════════════════════════

def cmd_run(rootfs: str, command: list[str], hostname: str,
            mem_mb: int, cpu_weight: int) -> None:
    """
    Startet einen Container. Das ist die Kernlogik – entspricht 'docker run'.

    Ablauf:
      ┌─ Parent-Prozess ───────────────────────────────────────────────────┐
      │  1. cgroup anlegen → schreibt eigene PID rein                      │
      │  2. unshare(NEWNS | NEWUTS | NEWIPC | NEWPID)                      │
      │     → neue Namespaces für Kinder erstellt                          │
      │  3. os.fork()                                                       │
      │     ├─ Child (PID 1 im neuen PID-Namespace) ──────────────────────┤
      │     │   4. sethostname()                                            │
      │     │   5. pivot_root() → Dateisystem isolieren                    │
      │     │   6. mount /proc                                              │
      │     │   7. exec(command) → Container-Prozess                       │
      │     └───────────────────────────────────────────────────────────── │
      │  4. waitpid() → warten bis Container fertig                        │
      │  5. cgroup aufräumen                                                │
      └────────────────────────────────────────────────────────────────────┘
    """
    rootfs = os.path.abspath(rootfs)
    if not os.path.isdir(rootfs):
        print(f"Fehler: rootfs '{rootfs}' existiert nicht.", file=sys.stderr)
        print("Tipp:  bash setup_rootfs.sh  → lädt Alpine Linux rootfs herunter")
        sys.exit(1)

    print("═" * 65)
    print("  own_container – Docker von Grund auf in Python")
    print("═" * 65)
    print(f"  Host-PID:   {os.getpid()}")
    print(f"  rootfs:     {rootfs}")
    print(f"  Hostname:   {hostname}")
    print(f"  Befehl:     {' '.join(command)}")
    print(f"  Memory:     {mem_mb} MB max")
    print(f"  CPU-Weight: {cpu_weight}")

    # ── cgroup anlegen ──────────────────────────────────────────────────────
    print(f"\n── 1. cgroup anlegen (Ressourcen-Limits) ───────────────────────")
    cg_path = None
    cg_name = f"own_container_{os.getpid()}"
    try:
        cg_path = setup_cgroup(cg_name, mem_mb, cpu_weight)
    except (PermissionError, OSError) as e:
        print(f"  [cgroup] Übersprungen (braucht root oder cgroup-Delegation): {e}")

    # ── Namespaces erstellen ────────────────────────────────────────────────
    print(f"\n── 2. Namespaces erstellen ─────────────────────────────────────")
    namespace_flags = CLONE_NEWNS | CLONE_NEWUTS | CLONE_NEWIPC | CLONE_NEWPID
    try:
        unshare(namespace_flags)
        print(f"  [namespaces] Mount + UTS + IPC + PID Namespace erstellt")
        print(f"  [namespaces] Hinweis: PID-Namespace gilt erst für Kinder (fork nötig)")
    except PermissionError:
        print("Fehler: Namespaces erstellen erfordert root-Rechte.", file=sys.stderr)
        print("Lösung: sudo python3 own_container.py run ...")
        sys.exit(1)

    # ── Fork: Kind wird PID 1 im neuen PID-Namespace ───────────────────────
    print(f"\n── 3. fork() – Kind-Prozess wird PID 1 im Container ───────────")
    pid = os.fork()

    if pid == 0:
        # ═══ KIND-PROZESS (Container) ═════════════════════════════════════
        child_main(rootfs, hostname, command)
        sys.exit(1)  # wird nie erreicht (exec übernimmt)

    # ═══ ELTERN-PROZESS (Host) ════════════════════════════════════════════
    print(f"  [parent] Container läuft als Host-PID {pid} / Container-PID 1")
    print(f"  [parent] Warte auf Container...\n")

    exit_code = 0
    try:
        _, status = os.waitpid(pid, 0)
        exit_code = os.waitstatus_to_exitcode(status)
        print(f"\n── Container beendet ───────────────────────────────────────────")
        print(f"  Exit-Code: {exit_code}")
    except KeyboardInterrupt:
        print("\n  Unterbrochen – beende Container...")
        try:
            os.kill(pid, signal.SIGTERM)
            os.waitpid(pid, 0)
        except OSError:
            pass
        exit_code = 130
    finally:
        if cg_path:
            cleanup_cgroup(cg_path)
            print(f"  cgroup '{cg_name}' aufgeräumt")

    sys.exit(exit_code)


# ══════════════════════════════════════════════════════════════════════════════
# CLI-Parsing
# ══════════════════════════════════════════════════════════════════════════════

def usage() -> None:
    print(__doc__)
    print("Beispiele:")
    print("  sudo python3 own_container.py run ./rootfs /bin/sh")
    print("  sudo python3 own_container.py run ./rootfs /bin/echo Hallo Welt")
    print("  sudo python3 own_container.py run --mem=128 --cpu=50 --hostname=mybox ./rootfs /bin/sh")
    print()
    print("Optionen:")
    print("  --mem=<MB>       Memory-Limit in MB (Standard: 256)")
    print("  --cpu=<weight>   CPU-Weight 1–10000 (Standard: 100)")
    print("  --hostname=<name> Hostname im Container (Standard: container)")


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        usage()
        sys.exit(0)

    if args[0] != "run":
        print(f"Unbekannter Befehl: '{args[0]}'", file=sys.stderr)
        usage()
        sys.exit(1)

    args = args[1:]

    # Optionen parsen
    mem_mb     = 256
    cpu_weight = 100
    hostname   = "container"

    while args and args[0].startswith("--"):
        opt = args.pop(0)
        if "=" not in opt:
            print(f"Ungültige Option: {opt}", file=sys.stderr)
            sys.exit(1)
        key, val = opt[2:].split("=", 1)
        if key == "mem":
            mem_mb = int(val)
        elif key == "cpu":
            cpu_weight = int(val)
        elif key == "hostname":
            hostname = val
        else:
            print(f"Unbekannte Option: --{key}", file=sys.stderr)
            sys.exit(1)

    if len(args) < 2:
        print("Fehler: rootfs-Pfad und Befehl sind erforderlich.", file=sys.stderr)
        usage()
        sys.exit(1)

    rootfs  = args[0]
    command = args[1:]

    cmd_run(rootfs, command, hostname, mem_mb, cpu_weight)


if __name__ == "__main__":
    main()
