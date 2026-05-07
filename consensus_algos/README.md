# Consensus Algorithms — Raft mit etcd auf Minikube

## Was ist Raft?

Raft ist ein Konsensus-Algorithmus, der sicherstellt, dass mehrere Nodes sich auf denselben Zustand einigen — auch wenn einzelne ausfallen.

### Kernkonzepte

| Konzept | Beschreibung |
|---|---|
| **Leader** | Ein Node koordiniert alle Writes |
| **Follower** | Empfangen Writes vom Leader, bestätigen sie |
| **Term** | Amtszeit eines Leaders (wie Legislaturperiode) |
| **Heartbeat** | Leader sendet regelmäßig "ich lebe" an Follower |
| **Election Timeout** | Kein Heartbeat empfangen → Follower startet Wahl |
| **Quorum** | Mehrheit muss bestätigen bevor ein Write committed wird (z.B. 2 von 3) |

### Ablauf eines Writes

```
Client: "setze x=5"
     │
     ▼
Leader: schreibt "x=5" in Log
     │
     ├──► Follower A: "append x=5" → OK
     ├──► Follower B: "append x=5" → OK
     └──► Follower C: (offline)

Quorum erreicht (2 von 3) → committed!
Leader antwortet Client: "OK"
```

### Leader Election

1. Follower bekommt kein Heartbeat (Election Timeout, zufällig 150-300ms)
2. Erhöht Term, wird Candidate, stimmt für sich selbst
3. Schickt RequestVote an alle anderen
4. Bekommt Mehrheit → wird neuer Leader
5. Sendet sofort Heartbeats

### Split-Brain

Bei Netzwerk-Partition kann nur die Seite mit **Mehrheit** Writes committen. Die Minderheit ist blockiert. Nach Heilung übernimmt die Minderheit den Zustand der Mehrheit.

→ Deshalb immer ungerade Anzahl: 3, 5, 7 Nodes.

---

## Setup

### Voraussetzungen

```bash
# Minikube installieren
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube

# kubectl installieren
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install kubectl /usr/local/bin/kubectl

# Minikube starten
minikube start --driver=docker
```

### etcd-Cluster deployen

```bash
kubectl create namespace etcd-demo
kubectl apply -f etcd-cluster.yaml
kubectl -n etcd-demo get pods -w  # warten bis alle 3 Running
```

---

## Befehle

### Cluster-Status

```bash
# Wer ist Leader? (von jedem Pod aus möglich)
kubectl -n etcd-demo exec etcd-0 -- etcdctl endpoint status --cluster -w table

# Einzelnen Node-Status
kubectl -n etcd-demo exec etcd-0 -- etcdctl endpoint status -w table
kubectl -n etcd-demo exec etcd-1 -- etcdctl endpoint status -w table
kubectl -n etcd-demo exec etcd-2 -- etcdctl endpoint status -w table

# Cluster Health
kubectl -n etcd-demo exec etcd-0 -- etcdctl endpoint health --cluster

# Member-Liste
kubectl -n etcd-demo exec etcd-0 -- etcdctl member list -w table
```

### Daten schreiben und lesen

```bash
# Auf etcd-0 schreiben
kubectl -n etcd-demo exec etcd-0 -- etcdctl put hello world
kubectl -n etcd-demo exec etcd-0 -- etcdctl put test123 "hallo"

# Von anderem Node lesen (Raft hat repliziert!)
kubectl -n etcd-demo exec etcd-1 -- etcdctl get hello
kubectl -n etcd-demo exec etcd-2 -- etcdctl get test123

# Alle Keys anzeigen
kubectl -n etcd-demo exec etcd-0 -- etcdctl get "" --prefix --keys-only
```

### Leader Kill — Election beobachten

```bash
# 1. Finde den Leader
kubectl -n etcd-demo exec etcd-0 -- etcdctl endpoint status --cluster -w table

# 2. Kill den Leader (z.B. etcd-0)
kubectl -n etcd-demo delete pod etcd-0

# 3. Sofort neuen Status prüfen (neuer Leader gewählt!)
kubectl -n etcd-demo exec etcd-1 -- etcdctl endpoint status --cluster -w table

# 4. Daten noch da?
kubectl -n etcd-demo exec etcd-1 -- etcdctl get hello

# 5. Pod kommt automatisch zurück (StatefulSet)
kubectl -n etcd-demo get pods -w
```

### Aufräumen

```bash
kubectl delete namespace etcd-demo
minikube stop     # Cluster stoppen
minikube delete   # Cluster komplett löschen
```

---

## Kubernetes Basics

### Architektur

```
Control Plane (Gehirn)
├── API-Server       → Einziger Eingang, alles kommuniziert hierüber
├── Scheduler        → Entscheidet welcher Pod auf welchen Node kommt
├── Controller-Manager → Vergleicht Soll vs. Ist, korrigiert
└── etcd             → Speichert gesamten Cluster-Zustand (nutzt Raft!)

Worker Nodes (Arbeiter)
├── kubelet          → Agent, empfängt Befehle
├── kube-proxy       → Netzwerk-Routing
└── Container Runtime → Führt Container aus
```

### Wichtige Konzepte

| Konzept | Beschreibung |
|---|---|
| **Node** | Maschine (VM/Container) auf der Pods laufen |
| **Pod** | Kleinste deploybare Einheit (1+ Container) |
| **Deployment** | Stateless Pods managen (zufällige Namen) |
| **StatefulSet** | Stateful Pods managen (stabile Namen: etcd-0, etcd-1, ...) |
| **Service** | Stabiler Netzwerk-Endpunkt für Pods |
| **Namespace** | Logische Trennung im Cluster |

### Nützliche kubectl-Befehle

```bash
kubectl get nodes              # Cluster-Nodes
kubectl get pods -A            # Alle Pods in allen Namespaces
kubectl get pods -n <ns>       # Pods in bestimmtem Namespace
kubectl describe pod <name>    # Details eines Pods
kubectl logs <pod>             # Logs eines Pods
kubectl delete pod <pod>       # Pod löschen (wird ggf. neu erstellt)
kubectl api-resources          # Alle verfügbaren Resource-Typen
```
