# Lesson Generator

Stateless FastAPI ML сервис для генерации темы урока, outline, типов заданий и секций через LLM-прокси.

## Что сделано для production
- Docker-упаковка (`Dockerfile`, `docker-compose.yml`)
- Асинхронные ML шаги генерации (`async/await`)
- Единый API-контракт ошибок (`error.code`, `error.message`, `error.details`)
- Глобальная обработка ошибок и централизованное логирование
- Опциональная авторизация входящих запросов по API-ключу (`APP_API_KEY`)

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
- `APP_API_KEY` (опционально, если задана - требуется в запросах)
- `APP_PORT` (внешний порт Docker, по умолчанию `8000`)
- `LOG_LEVEL` (опционально: `DEBUG`, `INFO`, `WARNING`, `ERROR`)
- `POLLINATIONS_API_KEY` (обязательная для `POST /ml/lesson/file/image/generate/`, берется на `https://enter.pollinations.ai`)
- `POLLINATIONS_IMAGE_API_URL` (по умолчанию: `https://gen.pollinations.ai/v1/images/generations`)
- `POLLINATIONS_IMAGE_MODEL` (по умолчанию: `flux`)

Пример в [`.env.example`](/Users/arseniy/PycharmProjects/LessonGenerator/.env.example).

## API
- `GET /health/` — проверка доступности сервиса и пулов моделей
- `POST /ml/lesson/topic/normalize/`
- `POST /ml/lesson/outline/create/`
- `POST /ml/lesson/outline/improve/`
- `POST /ml/lesson/section/task-types/`
- `POST /ml/lesson/section/generate/`
- `POST /ml/lesson/file/image/generate/`

Подробный контракт в [`docs/API_CONTRACT.md`](/Users/arseniy/PycharmProjects/LessonGenerator/docs/API_CONTRACT.md).

## Авторизация API
Если задан `APP_API_KEY`, все запросы должны содержать ключ в одном из вариантов:

- `X-API-Key: <APP_API_KEY>`
- `Authorization: Bearer <APP_API_KEY>`

Пример:
```bash
curl -X POST 'http://localhost:8000/ml/lesson/topic/normalize/' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: <APP_API_KEY>' \
  -d '{"user_request":"Present Continuous"}'
```

## Формат ошибок
Единый формат:
```json
{
  "error": {
    "code": "invalid_generation_result",
    "message": "Generated content does not match expected schema.",
    "details": {
      "field": "tasks[1].fill_gaps.answers",
      "reason": "answers count does not match placeholders count"
    }
  }
}
```

Коды:
- `unauthorized` — отсутствует или неверный API ключ
- `invalid_request` — невалидный request payload
- `invalid_generation_result` — LLM вернул контент, не соответствующий контракту
- `internal_error` — ошибка инфраструктуры/конфигурации
