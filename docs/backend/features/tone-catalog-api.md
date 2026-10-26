# Tone catalog API

`GET /api/v1/tones` returns the ordered, curated writing-tone options for the
blog brief form. The endpoint is public because the catalog contains no
user-specific data.

```json
{
  "items": [
    {
      "value": "practical",
      "label": "Practical",
      "description": "Clear, useful guidance readers can put into action."
    }
  ]
}
```

The endpoint reads PostgreSQL's `tone_catalog` table and stores the serialized
response in Redis under `catalog:tones:v1` for 172,800 seconds (48 hours). The
database remains authoritative; cache read/write failures do not prevent the
endpoint from serving the catalog.

The table uses the PostgreSQL `blog_tone_value` enum and is seeded with ten
options. This catalog is additive: `POST /api/v1/blogs/generate` continues to
accept the existing free-text `tone` field, and `blog_sessions.tone` remains a
string so saved and custom tone values stay compatible.

Apply the Alembic migration `d5e6f7a8b9c0` before calling this endpoint.
