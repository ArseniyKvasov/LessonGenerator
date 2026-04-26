# ML API Contract

ML service is stateless.
Backend stores jobs, progress, sections, files and final lessons.

## Common Error Format

```json
{
  "error": {
    "code": "invalid_request | invalid_generation_result | internal_error | provider_error | timeout",
    "message": "Human-readable error message.",
    "details": {}
  }
}
```

## Available Task Types

- `note`
- `test`
- `true_false`
- `file`
- `match_cards`
- `word_list`
- `fill_gaps`

## Task JSON Schemas

### `note`
```json
{
  "note": {
    "title": "str",
    "content": "str markdown"
  }
}
```

### `test`
```json
{
  "test": {
    "questions": [
      {
        "question": "str",
        "options": [
          {
            "option": "str",
            "is_correct": true
          }
        ]
      }
    ]
  }
}
```

### `true_false`
```json
{
  "true_false": {
    "statements": [
      {
        "statement": "str",
        "is_true": true
      }
    ]
  }
}
```

### `file`
```json
{
  "file": {
    "image_base64": "str",
    "mime_type": "image/png | image/jpeg | image/webp",
    "alt": "str"
  }
}
```

### `match_cards`
```json
{
  "match_cards": {
    "pairs": [
      {
        "left": "str",
        "right": "str"
      }
    ]
  }
}
```

### `word_list`
```json
{
  "word_list": {
    "pairs": [
      {
        "word": "str",
        "translation": "str"
      }
    ]
  }
}
```

### `fill_gaps`
```json
{
  "fill_gaps": {
    "content": "str markdown",
    "answers": ["str"]
  }
}
```

## Endpoints

### POST `/ml/lesson/topic/form/`
Request:
```json
{ "user_request": "Present Continuous" }
```
Response:
```json
{ "topic": "Present Continuous: Form and Usage" }
```

### POST `/ml/lesson/subject/define/`
Request:
```json
{ "topic": "Present Continuous: Form and Usage" }
```
Response:
```json
{ "subject": "language" }
```

### POST `/ml/lesson/sections/form/`
Request:
```json
{
  "topic": "Present Continuous: Form and Usage",
  "subject": "language"
}
```
Response:
```json
{
  "sections": [
    { "title": "Form Basics" },
    { "title": "Usage Rules" },
    { "title": "Signal Words" }
  ]
}
```

### POST `/ml/lesson/references/form/`
Request:
```json
{
  "topic": "Present Continuous: Form and Usage",
  "subject": "language",
  "sections": [
    { "title": "Form Basics" },
    { "title": "Usage Rules" }
  ]
}
```
Response:
```json
{
  "references": [
    { "section": "Form Basics", "reference": "Subject + am/is/are + Verb-ing" },
    { "section": "Usage Rules", "reference": "Actions happening now or temporary situations" }
  ]
}
```

### POST `/ml/lesson/task-types/define/`
Request:
```json
{
  "topic": "Present Continuous: Form and Usage",
  "subject": "language",
  "sections": [
    { "title": "Form Basics", "reference": "Subject + am/is/are + Verb-ing" },
    { "title": "Usage Rules", "reference": "Actions happening now or temporary situations" }
  ],
  "available_task_types": ["note", "test", "true_false", "file", "match_cards", "word_list", "fill_gaps"]
}
```
Response:
```json
{
  "sections": [
    { "section": "Form Basics", "task_types": ["note", "fill_gaps"] },
    { "section": "Usage Rules", "task_types": ["note", "true_false"] }
  ]
}
```

### POST `/ml/lesson/section/generate/`
Request:
```json
{
  "topic": "Present Continuous: Form and Usage",
  "subject": "language",
  "section": {
    "title": "Form Basics",
    "reference": "Subject + am/is/are + Verb-ing",
    "task_types": ["note", "fill_gaps"]
  },
  "previous_sections": [],
  "next_sections": [
    { "title": "Usage Rules", "reference": "Actions happening now or temporary situations" }
  ]
}
```
Response:
```json
{
  "tasks": [
    {
      "note": {
        "title": "Present Continuous Structure",
        "content": "Use **Subject + am/is/are + Verb-ing**."
      }
    },
    {
      "fill_gaps": {
        "content": "I ___ reading now.",
        "answers": ["am"]
      }
    }
  ]
}
```

### POST `/ml/lesson/image/generate/`
Request:
```json
{
  "topic": "Present Continuous: Form and Usage",
  "subject": "language",
  "section": {
    "title": "Speaking Practice",
    "reference": "Describe current actions in the room"
  },
  "image_goal": "Create an image for speaking practice. Students should be able to describe actions using Present Continuous.",
  "style": "clean educational illustration",
  "aspect_ratio": "16:9"
}
```
Response:
```json
{
  "file": {
    "image_base64": "iVBORw0KGgoAAAANSUhEUgAA...",
    "mime_type": "image/png",
    "alt": "A classroom scene where students are reading, writing, talking and looking at a laptop."
  }
}
```

## Validation Rules

- Topic: max 120 chars.
- Subject: one of `math | language | physics | chemistry | other`.
- Sections: 3-8; title is 1-2 words; no duplicates.
- References: exactly one per section; short teaching-focused text.
- Task types: 1-4 per section; from available list; no duplicates.
- Section tasks: each task has exactly one allowed key and belongs to requested `task_types`.
- `test`: 1-5 questions; 2-4 options; exactly one correct option.
- `true_false`: 2-8 statements.
- `match_cards`: 2-8 pairs.
- `word_list`: 3-12 pairs.
- `fill_gaps`: markdown content, answers are string array and must match blanks order.
- `file`: `image_base64` required, `mime_type` in `image/png|image/jpeg|image/webp`, `alt` required.
