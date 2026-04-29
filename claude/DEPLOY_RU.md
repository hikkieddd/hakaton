# Деплой в России

Самый надежный вариант для показа из РФ: VPS в Timeweb Cloud, Beget, Selectel, VK Cloud или Yandex Cloud.
Приложение уже упаковано в Docker.

## Быстрый запуск на VPS с Docker

1. Загрузить папку проекта на сервер:

```bash
scp -r ./claude root@SERVER_IP:/opt/budget-constructor
```

2. Зайти на сервер:

```bash
ssh root@SERVER_IP
cd /opt/budget-constructor
```

3. Запустить:

```bash
docker compose up -d --build
```

4. Открыть:

```text
http://SERVER_IP/
```

## Если порт 80 занят

В `docker-compose.yml` заменить:

```yaml
ports:
  - "80:8765"
```

на:

```yaml
ports:
  - "8765:8765"
```

и открыть:

```text
http://SERVER_IP:8765/
```

## Проверка

```bash
curl http://localhost/api/health
docker logs budget-constructor --tail=100
```
