# own_container – Docker von Grund auf

Zeigt die Linux-Kernel-Features, die Docker/containerd/runc unter der Haube benutzen –
erst als 5-Zeiler in Bash, dann als vollständige Python-Implementierung.

## Was Docker wirklich macht

```
docker run --memory=256m ubuntu /bin/bash
     │
     ├── 1. cgroups     → Memory/CPU limitieren
     ├── 2. Namespaces  → Prozesse/Hostname/Dateisystem isolieren
     ├── 3. pivot_root  → "/" des Containers auf Image-Verzeichnis setzen
     └── 4. exec        → Befehl starten (wird PID 1 im Container)
```

## Einstieg: Container in 5 Zeilen Bash

Bash-Tools wie `unshare` und `chroot` sind direkte 1:1-Wrapper der Kernel-Syscalls –
damit sieht man das Prinzip am klarsten:

```bash
sudo unshare --pid --mount --uts --fork \
  bash -c "hostname container && mount --make-rprivate / && mount -t proc proc ./rootfs/proc && exec chroot ./rootfs /bin/sh"
```

Oder Schritt für Schritt mit `container_simple.sh`:

```bash
bash setup_rootfs.sh              # Alpine Linux rootfs herunterladen
sudo bash container_simple.sh ./rootfs

# Im Container:
hostname    # → container      (eigener UTS-Namespace)
ps aux      # → nur 2 Prozesse (eigener PID-Namespace, PID 1!)
ls /        # → Alpine Linux   (chroot auf ./rootfs)
exit
```

Jede Zeile entspricht genau einem Syscall:

| Bash-Befehl | Syscall | Was er macht |
|---|---|---|
| `unshare --pid --mount --uts` | `unshare()` | Neue Namespaces erstellen |
| `hostname container` | `sethostname()` | Hostname im UTS-Namespace setzen |
| `mount -t proc proc /proc` | `mount()` | /proc einhängen |
| `chroot ./rootfs` | `chroot()` | "/" des Prozesses wechseln |

---

## Konzepte im Detail

### 1. Linux Namespaces

Namespaces sind der Kern der Isolation. Jeder Container lebt in eigenen Namespaces:

| Namespace | Flag          | Was wird isoliert?                          |
|-----------|---------------|---------------------------------------------|
| PID       | CLONE_NEWPID  | Prozess-IDs – Container sieht nur sich selbst, hat PID 1 |
| Mount     | CLONE_NEWNS   | Dateisystem-Sicht – eigene Mount-Table      |
| UTS       | CLONE_NEWUTS  | Hostname und Domainname                     |
| IPC       | CLONE_NEWIPC  | Message Queues, Semaphoren, Shared Memory   |
| Network   | CLONE_NEWNET  | Netzwerkinterfaces, Routing, Firewall       |
| User      | CLONE_NEWUSER | UID/GID-Mapping (rootless Container)        |

```python
# So erstellt man Namespaces in C/Python:
unshare(CLONE_NEWNS | CLONE_NEWUTS | CLONE_NEWIPC | CLONE_NEWPID)
# Dann fork() → Kind ist PID 1 im neuen PID-Namespace
```

### 2. cgroups v2 (Control Groups)

cgroups limitieren, wie viele Ressourcen ein Container nutzen darf.
Das Kernel-Interface ist das Dateisystem unter `/sys/fs/cgroup/`.

```bash
# Was own_container.py macht:
mkdir /sys/fs/cgroup/own_container_1234/
echo "268435456" > /sys/fs/cgroup/own_container_1234/memory.max   # 256 MB
echo "100"       > /sys/fs/cgroup/own_container_1234/cpu.weight
echo "1234"      > /sys/fs/cgroup/own_container_1234/cgroup.procs # PID eintragen
```

### 3. pivot_root statt chroot

`chroot` ist ein einfacher Pfad-Trick – der Kernel-Zugriff bleibt.
`pivot_root` tauscht den echten Root-Mount-Point aus:

```
Vor pivot_root:          Nach pivot_root:
  /          (Host)        /          (Container-rootfs = Alpine)
  ├── bin                  ├── bin
  ├── home                 ├── etc
  ├── sys/fs/cgroup        ├── proc    ← neu eingehängt
  └── ...                  └── ...    (kein Zugriff auf Host mehr)
```

### 4. Fork + Exec Muster

```
Parent (Host)                    Kind (Container)
─────────────────                ──────────────────────────────
setup_cgroup()                   
unshare(NEWNS|NEWPID|...)
os.fork() ──────────────────────► PID 1 im neuen Namespace
waitpid()                        sethostname("container")
                                 pivot_root(rootfs)
                                 mount("/proc")
                                 exec("/bin/sh")   ← kein Python mehr!
```

## Dateien

```
own_container/
├── container_simple.sh  # Container in 30 Zeilen Bash (zum Verstehen)
├── own_container.py     # vollständige Python-Implementierung (~300 Zeilen)
├── setup_rootfs.sh      # lädt Alpine Linux rootfs herunter
└── rootfs/              # Alpine rootfs (nach setup_rootfs.sh)
    ├── bin/
    ├── etc/
    ├── proc/
    └── ...
```

## Schnellstart (Bash)

```bash
bash setup_rootfs.sh                      # Alpine rootfs herunterladen
sudo bash container_simple.sh ./rootfs    # Container starten
```

## Schnellstart (Python – mit cgroups)

```bash
sudo python3 own_container.py run ./rootfs /bin/sh

# Optionen:
#   --mem=<MB>          Memory-Limit (Standard: 256 MB)
#   --cpu=<weight>      CPU-Weight 1–10000 (Standard: 100)
#   --hostname=<name>   Hostname im Container (Standard: container)
```

## Was fehlt (was Docker noch macht)

- **OverlayFS** – Docker-Images sind Schichten (Copy-on-Write). Wir nutzen ein simples Verzeichnis.
- **Network Namespace** – wir könnten `veth`-Paare + iptables-NAT einrichten (wie `docker network`)
- **User Namespace** – rootless Container (UID-Mapping, kein root nötig)
- **Capabilities** – Docker droppt gefährliche Linux-Capabilities (`CAP_SYS_ADMIN` etc.)
- **Seccomp** – Syscall-Filter (blockiert gefährliche Syscalls im Container)
- **SELinux/AppArmor** – Mandatory Access Control
- **Image-Format** – OCI Image Spec (tar-Layer + JSON Manifest)

## Weiterführend

- [Liz Rice: Containers from Scratch (Go)](https://github.com/lizrice/containers-from-scratch) – der Klassiker
- `man 7 namespaces` – Linux-Manpage zu Namespaces
- `man 7 cgroups` – Linux-Manpage zu cgroups
- `man 2 pivot_root` – Syscall-Dokumentation
- [runc](https://github.com/opencontainers/runc) – die echte OCI Container-Runtime
