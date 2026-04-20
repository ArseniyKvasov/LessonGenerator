# API Contract

Base URL: `/`

## Общие правила
- Все ошибки возвращаются в едином формате `ErrorResponse`.
- В каждый ответ добавляется заголовок `X-Request-ID`.
- Можно передать свой `X-Request-ID` в запросе для трассировки.
- Все эндпоинты требуют API ключ.

## Авторизация
Передавайте ключ в одном из заголовков:
- `X-API-Key: <APP_API_KEY>`
- `Authorization: Bearer <APP_API_KEY>`

При неверном/отсутствующем ключе вернется `401`.

## GET `/health/`
Проверка доступности API и пулов моделей.

### 200 OK
```json
{
  "status": "ok",
  "simple_available": ["llama-3.1-8b-instant"],
  "strong_available": ["llama-3.3-70b-versatile"],
  "simple_unavailable": [],
  "strong_unavailable": []
}
```

### 401 Unauthorized
```json
{
  "status": "error",
  "code": "unauthorized",
  "message": "Valid API key is required",
  "request_id": "8f6f8a95-9b2e-4580-bec3-7d297fa0f9bd"
}
```

### 503 / 500
```json
{
  "status": "error",
  "code": "model_unavailable_error",
  "message": "No available models in required pool(s)...",
  "request_id": "8f6f8a95-9b2e-4580-bec3-7d297fa0f9bd"
}
```

## POST `/generate/`
Генерация структуры урока и заданий.

### Request
```json
{
  "request": "Создай интерактивный урок по теме квадратичной функции"
}
```

### 200 OK
Возвращает `LessonFlowResponse`:
- `topic`: тема урока
- `subject`: предмет (`math`, `language`, `physics`, `chemistry`, `other`)
- `sections`: список разделов
- `references`: опорные материалы по разделам
- `section_task_types`: типы задач по разделам
- `tasks_by_section`: сгенерированные задания
- `task_contracts`: контракты полей для типов задач
- `models`: стратегия выбора моделей

### 422 Validation Error
```json
{
  "status": "error",
  "code": "validation_error",
  "message": "Request payload is invalid",
  "request_id": "fca6a47e-e1be-44cc-b60f-145f6eb11d2a"
}
```

### 503 Service Unavailable
```json
{
  "status": "error",
  "code": "flow_generation_error",
  "message": "Step sections failed after 3 attempts...",
  "request_id": "fca6a47e-e1be-44cc-b60f-145f6eb11d2a"
}
```

### 500 Internal Server Error
```json
{
  "status": "error",
  "code": "internal_server_error",
  "message": "Unexpected server error",
  "request_id": "fca6a47e-e1be-44cc-b60f-145f6eb11d2a"
}
```
