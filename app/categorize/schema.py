from __future__ import annotations

from typing import Any, Dict

RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "categorization_response",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "users": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "user_id": {"type": "integer"},
                            "category": {"type": "string"},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "summary": {"type": "string"},
                            "worth_checking": {"type": "boolean"},
                            "reasoning": {"type": "string"},
                            "user_metadata": {
                                "type": "object",
                                "properties": {
                                    "age": {"type": ["integer", "null"]},
                                    "city": {"type": ["string", "null"]},
                                    "country": {"type": ["string", "null"]},
                                    "profession": {"type": ["string", "null"]},
                                    "experience_years": {"type": ["integer", "null"]},
                                    "languages": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "links": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "contact_info": {"type": ["string", "null"]},
                                },
                                "required": [
                                    "age", "city", "country", "profession",
                                    "experience_years", "languages", "links",
                                    "contact_info",
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "required": [
                            "user_id", "category", "tags", "summary",
                            "worth_checking", "reasoning", "user_metadata",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["users"],
            "additionalProperties": False,
        },
    },
}

SCHEMA_VERSION = "v2.0"
