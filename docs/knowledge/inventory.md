# Инвентарь homelab

Homelab на одном Docker-хосте (Intel N100): агент Heimdall крутится на том же хосте, что и сервисы.

## postgres
- container: postgres
- related: postgres-exporter
- restartable: false
- logs: Loki `{container="postgres"}`
- metrics: `pg_up` / postgres-exporter

## traefik
- container: traefik
- restartable: false

## tunnel (local only)
- containers: 3x-ui
- restartable: false
- remote VPN host is out of scope for v1

## loki / victoriametrics
- observability; coverage is incomplete on purpose
- restartable: false

## vaultwarden
- restartable: false
