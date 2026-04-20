# Lesson Generator

Production-ready FastAPI сервис для генерации структуры урока и интерактивных заданий через LLM-прокси.

## Что сделано для production
- Docker-упаковка (`Dockerfile`, `docker-compose.yml`)
- Асинхронный pipeline генерации (`async/await` + параллельная генерация задач по секциям)
- Единый API-контракт ошибок с `request_id`
- Глобальная обработка ошибок и централизованное логирование
- Обязательная авторизация входящих запросов по API-ключу

## Стек
- Python 3.12
- FastAPI
- Uvicorn
- Pydantic v2
- httpx (асинхронный HTTP клиент)

## Быстрый старт (локально)
1. Создайте и заполните `.env`:
```bash
cp .env.example .env
```
2. Установите зависимости:
```bash
pip install -r requirements.txt
```
3. Запустите API:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Swagger: `http://localhost:8000/docs`

## Запуск в Docker
### Через Docker Compose
Внешний порт настраивается через `APP_PORT` в `.env`.

```bash
docker compose up --build -d
```

### Через Docker CLI
```bash
docker build -t lesson-generator .
docker run --env-file .env -p 8000:8000 lesson-generator
```

## Переменные окружения
Сервис читает конфигурацию из `.env`.

- `PROXY_API_KEY` (обязательная)
- `PROXY_API_URL` (по умолчанию: `http://91.103.253.236/generate`)
- `PROXY_MAX_TOKENS` (по умолчанию: `4096`)
- `APP_API_KEY` (обязательная, ключ для доступа к API)
- `APP_PORT` (внешний порт Docker, по умолчанию `8000`)
- `LOG_LEVEL` (опционально: `DEBUG`, `INFO`, `WARNING`, `ERROR`)

Пример в [`.env.example`](/Users/arseniy/PycharmProjects/LessonGenerator/.env.example).

## API
- `GET /health/` — проверка доступности сервиса и пулов моделей
- `POST /generate/` — генерация структуры урока

Подробный контракт в [`docs/API_CONTRACT.md`](/Users/arseniy/PycharmProjects/LessonGenerator/docs/API_CONTRACT.md).

## Авторизация API
Все запросы должны содержать ключ `APP_API_KEY` в одном из вариантов:

- `X-API-Key: <APP_API_KEY>`
- `Authorization: Bearer <APP_API_KEY>`

Пример:
```bash
curl -X POST 'http://localhost:8000/generate/' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: <APP_API_KEY>' \
  -d '{"request":"Сделай урок по фотосинтезу"}'
```

## Формат ошибок
Единый формат:
```json
{
  "status": "error",
  "code": "string",
  "message": "string",
  "request_id": "uuid"
}
```

Коды:
- `unauthorized` — отсутствует или неверный API ключ
- `validation_error` — невалидный payload
- `config_error` — ошибка конфигурации
- `proxy_error` — ошибка внешнего прокси
- `flow_generation_error` — ошибка генерации пайплайна
- `model_unavailable_error` — нет доступных моделей
- `internal_server_error` — непредвиденная ошибка
