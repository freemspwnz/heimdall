# Postgres: unhealthy / нет логов exporter

## Когда

Контейнер `postgres` в статусе unhealthy или restarting; в Loki нет логов `postgres-exporter`; метрика `pg_up` отсутствует или равна 0; пользователь спрашивает «что с базой?».

## Куда смотреть

1. `docker inspect postgres` — статус, healthcheck, exit code, последний restart.
2. Loki: `{container="postgres"}` за последние 15–30 минут.
3. VictoriaMetrics: `pg_up` (postgres-exporter) — если метрики нет, exporter может быть мёртв или не настроен.
4. Контейнер `postgres-exporter` — `docker ps` / `docker inspect`, логи (если есть в Loki).

## Рестарт

`docker restart postgres` допустим (restartable: true), но **режет активные соединения** — все клиенты (Gitea, wedding DB и др.) потеряют сессии. Предлагать только после сбора фактов и с явным предупреждением. Если диск full или нужна ручная диагностика — отчёт без рестарта.
