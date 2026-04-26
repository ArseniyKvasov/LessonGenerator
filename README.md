# Lesson Generator

Stateless FastAPI ML сервис для генерации интерактивных уроков по контракту `ML API CONTRACT`.

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
- `PROXY_API_KEY` (обязательная)
- `PROXY_API_URL` (по умолчанию: `http://91.103.253.236/generate`)
- `PROXY_MAX_TOKENS` (по умолчанию: `4096`)
- `APP_API_KEY` (опционально, если задана - требуется в запросах)
- `APP_PORT` (внешний порт Docker, по умолчанию `8000`)
- `LOG_LEVEL` (опционально: `DEBUG`, `INFO`, `WARNING`, `ERROR`)
- `POLLINATIONS_API_KEY` (обязательная для `POST /ml/lesson/image/generate/`)
- `POLLINATIONS_IMAGE_API_URL` (по умолчанию: `https://gen.pollinations.ai/v1/images/generations`)
- `POLLINATIONS_IMAGE_MODEL` (по умолчанию: `flux`)

Пример в [`.env.example`](/Users/arseniy/PycharmProjects/LessonGenerator/.env.example).

## API
- `GET /health/`
- `POST /ml/lesson/topic/form/`
- `POST /ml/lesson/subject/define/`
- `POST /ml/lesson/sections/form/`
- `POST /ml/lesson/references/form/`
- `POST /ml/lesson/task-types/define/`
- `POST /ml/lesson/section/generate/`
- `POST /ml/lesson/image/generate/`

Подробный контракт в [`docs/API_CONTRACT.md`](/Users/arseniy/PycharmProjects/LessonGenerator/docs/API_CONTRACT.md).

## Формат ошибок
```json
{
  "error": {
    "code": "invalid_request | invalid_generation_result | internal_error | provider_error | timeout",
    "message": "Human-readable error message.",
    "details": {}
  }
}
```
