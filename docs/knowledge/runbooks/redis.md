# Redis: состояние сервиса

## Когда

Пользователь спрашивает про Redis или его доступность.

## Куда смотреть

Статус контейнера `redis` и его логи за последние 30 минут.

## Рестарт

Рестарт `redis` запрещён.

```heimdall-calls
docker_inspect name=redis
loki_query query={container="redis"} since=30m
```
