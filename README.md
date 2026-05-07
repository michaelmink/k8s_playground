# k8s_playground

Hands-on Experimente mit Kubernetes auf Minikube. Jeder Ordner ist ein eigenständiges Beispiel mit eigener README und YAML-Dateien zum Deployen.

## Voraussetzungen

- Docker
- Minikube (`minikube start --driver=docker`)
- kubectl

## Beispiele

| Ordner | Thema |
|---|---|
| `consensus_algos/` | Raft-Konsensus mit einem 3-Node etcd-Cluster |
| `networking/` | Services, ClusterIP, NodePort, DNS, Load Balancing |