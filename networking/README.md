# Kubernetes Networking Demo

## Konzepte

```
┌─────────────────────────────────────────────────────────┐
│ Cluster                                                 │
│                                                         │
│  ┌─ Service "nginx-clusterip" (ClusterIP) ──────────┐  │
│  │  Feste IP, nur intern erreichbar                  │  │
│  │     │         │         │                         │  │
│  │  Pod nginx-1  Pod nginx-2  Pod nginx-3            │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ┌─ Service "nginx-nodeport" (NodePort:30080) ──────┐  │
│  │  Von außen erreichbar über <NodeIP>:30080         │  │
│  │     │         │         │                         │  │
│  │  Pod nginx-1  Pod nginx-2  Pod nginx-3            │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  Pod "client" → curl nginx-clusterip → Load Balanced!   │
└─────────────────────────────────────────────────────────┘
```

## Setup

```bash
kubectl create namespace networking-demo
kubectl apply -f 01-deployment.yaml
kubectl apply -f 02-services.yaml
kubectl apply -f 03-client.yaml
kubectl -n networking-demo get pods -w  # warten bis alles Running
```

## Experimente

### 1. ClusterIP — interner Zugriff

Vom Client-Pod aus den Service aufrufen:

```bash
# Einmal aufrufen
kubectl -n networking-demo exec client -- curl -s nginx-clusterip

# Mehrfach aufrufen — beobachte welcher Pod antwortet (Load Balancing)
kubectl -n networking-demo exec client -- curl -s nginx-clusterip | grep "Server name"

# DNS funktioniert auch mit vollem Namen
kubectl -n networking-demo exec client -- curl -s nginx-clusterip.networking-demo.svc.cluster.local
```

### 2. NodePort — externer Zugriff

Von deinem Host aus:

```bash
# Minikube IP herausfinden
minikube ip

# Zugriff über NodePort
curl http://$(minikube ip):30080
```

### 3. Service-Details anschauen

```bash
# Welche Endpoints hat der Service? (= welche Pod-IPs)
kubectl -n networking-demo get endpoints nginx-clusterip

# Service-Details
kubectl -n networking-demo describe service nginx-clusterip
```

### 4. Pod killen — Service routet automatisch um

```bash
# Pods anzeigen
kubectl -n networking-demo get pods -o wide

# Einen Pod killen
kubectl -n networking-demo delete pod <pod-name>

# Service hat sofort einen Endpoint weniger, dann kommt neuer Pod
kubectl -n networking-demo get endpoints nginx-clusterip -w
```

### 5. Skalieren — Service bemerkt neue Pods

```bash
# Auf 5 Replicas hochskalieren
kubectl -n networking-demo scale deployment nginx --replicas=5

# Endpoints wachsen mit
kubectl -n networking-demo get endpoints nginx-clusterip
```

## Aufräumen

```bash
kubectl delete namespace networking-demo
```

## Zusammenfassung

| Service-Typ | Erreichbar von | Use Case |
|---|---|---|
| `ClusterIP` | Nur Pods im Cluster | Interne Kommunikation (DB, Cache) |
| `NodePort` | Außen via `<NodeIP>:<30000-32767>` | Dev/Test, einfaches Exponieren |
| `LoadBalancer` | Außen via Cloud-LB | Produktion (GKE/EKS/AKS) |

**Wie findet der Service seine Pods?** Über `selector: app: nginx` — jeder Pod mit diesem Label wird ein Endpoint.

**DNS:** Jeder Service bekommt automatisch `<name>.<namespace>.svc.cluster.local`.
