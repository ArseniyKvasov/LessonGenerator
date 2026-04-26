# ML Service API Contract

Base URL: `/`

## Common Error Format
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

Error codes used by this ML service:
- `400 invalid_request`
- `401 unauthorized`
- `422 invalid_generation_result`
- `500 internal_error`

## GET `/health/`
Technical health endpoint for model pools.

## POST `/ml/lesson/topic/normalize/`

Request:
```json
{
  "user_request": "Present Continuous"
}
```

Response 200:
```json
{
  "topic": "Present Continuous: Form and Usage",
  "subject": "language"
}
```

## POST `/ml/lesson/outline/create/`

Request:
```json
{
  "topic": "Present Continuous: Form and Usage",
  "subject": "language",
  "language": "english",
  "level": "A2",
  "lesson_format": "short"
}
```

Response 200:
```json
{
  "sections": [
    {
      "section_id": "form_basics",
      "title": "Form Basics",
      "reference": "Subject + am/is/are + verb-ing"
    }
  ]
}
```

Validation:
- `sections`: 3-8 items
- `section_id`: unique slug
- `title`: 1-3 words
- `reference`: short teaching reference

## POST `/ml/lesson/outline/improve/`

Request:
```json
{
  "topic": "Present Continuous: Form and Usage",
  "subject": "language",
  "language": "english",
  "level": "A2",
  "lesson_format": "short",
  "current_sections": [
    {
      "section_id": "form_basics",
      "title": "Form Basics",
      "reference": "Subject + am/is/are + verb-ing"
    }
  ],
  "improvement_prompt": "Add more speaking practice and make it easier"
}
```

Response 200:
```json
{
  "sections": [
    {
      "section_id": "form_basics",
      "title": "Form Basics",
      "reference": "Subject + am/is/are + verb-ing"
    }
  ]
}
```

## POST `/ml/lesson/section/task-types/`

Request:
```json
{
  "topic": "Present Continuous: Form and Usage",
  "subject": "language",
  "language": "english",
  "level": "A2",
  "section": {
    "section_id": "form_basics",
    "title": "Form Basics",
    "reference": "Subject + am/is/are + verb-ing"
  },
  "available_task_types": [
    "note",
    "test",
    "true_false",
    "file",
    "match_cards",
    "word_list",
    "fill_gaps"
  ]
}
```

Response 200:
```json
{
  "section_id": "form_basics",
  "task_types": ["note", "fill_gaps"]
}
```

Validation:
- `task_types`: 1-3 items
- each type must be from `available_task_types`

## POST `/ml/lesson/section/generate/`

Request:
```json
{
  "topic": "Present Continuous: Form and Usage",
  "subject": "language",
  "language": "english",
  "level": "A2",
  "section": {
    "section_id": "form_basics",
    "title": "Form Basics",
    "reference": "Subject + am/is/are + verb-ing",
    "task_types": ["note", "fill_gaps"]
  },
  "previous_sections": [],
  "task_schemas": {
    "note": { "content": "str markdown" },
    "fill_gaps": {
      "content": "str markdown with {{answer}}",
      "answers": ["str"]
    }
  }
}
```

Response 200:
```json
{
  "section_id": "form_basics",
  "tasks": [
    {
      "note": {
        "content": "Use **am/is/are + verb-ing** to form the Present Continuous."
      }
    }
  ],
  "image_requests": [
    {
      "task_index": 0,
      "image_prompt": "A clean educational illustration of a classroom."
    }
  ]
}
```

## POST `/ml/lesson/file/image/generate/`

Request:
```json
{
  "topic": "Present Continuous: Form and Usage",
  "subject": "language",
  "language": "english",
  "level": "A2",
  "section": {
    "section_id": "speaking_practice",
    "title": "Speaking Practice",
    "reference": "Describe current actions using Present Continuous"
  },
  "image_prompt": "A clean educational illustration of a classroom where students are reading, writing, and talking.",
  "style": "clean educational illustration",
  "aspect_ratio": "16:9"
}
```

Response 200:
```json
{
  "file": {
    "file_url": "https://cdn.example.com/generated/classroom-actions.png",
    "file_type": "image",
    "alt": "Students are doing different activities in a classroom."
  }
}
```
