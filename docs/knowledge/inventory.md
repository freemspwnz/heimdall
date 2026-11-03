# Инвентарь homelab

Homelab на одном Docker-хосте (Intel N100): агент Heimdall крутится на том же хосте, что и сервисы.

## host
- scope: все контейнеры хоста
- restartable: false

## postgres
- container: postgres
- related: postgres-exporter
- restartable: false
- logs: Loki `{container="postgres"}`
- metrics: `pg_up` / postgres-exporter

## redis
- container: redis
- restartable: false

## traefik
- container: traefik
- restartable: false

## tunnel
- containers: 3x-ui
- restartable: false

## loki / victoriametrics
- observability; coverage is incomplete on purpose
- restartable: false

## vaultwarden
- restartable: false
