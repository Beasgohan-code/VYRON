# ---------------------------------------------------------------------------
#  VYRON API — OpenAPI 3.1 description (served at /v1/openapi.json)
# ---------------------------------------------------------------------------
from __future__ import annotations

from aiohttp import web

from vyron.config import settings
from vyron.core.musicapi import SCOPES


def _base(request: web.Request) -> str:
    if settings.api_base:
        return f"{settings.api_base}/v1"
    proto = request.headers.get("X-Forwarded-Proto") or request.scheme
    host = request.headers.get("X-Forwarded-Host") or request.host
    return f"{proto}://{host}/v1"


TRACK = {
    "type": "object",
    "properties": {
        "video_id": {"type": "string"},
        "title": {"type": "string"},
        "artist": {"type": "string"},
        "duration": {"type": "integer"},
        "thumbnail": {"type": ["string", "null"]},
        "source": {"type": "string"},
        "url": {"type": "string"},
        "stream_url": {"type": "string"},
        "info_url": {"type": "string"},
        "lyrics_url": {"type": "string"},
    },
}

ERROR = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean", "const": False},
        "error": {"type": "string"},
        "code": {"type": "string"},
        "hint": {"type": "string"},
        "request_id": {"type": "string"},
    },
}

DOWNLOAD_JOB = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "job_id": {"type": "string"},
        "status": {
            "type": "string",
            "enum": ["queued", "running", "ready", "failed", "cancelled"],
        },
        "kind": {"type": "string", "enum": ["audio", "video"]},
        "video_id": {"type": "string"},
        "title": {"type": "string"},
        "artist": {"type": "string"},
        "progress": {"type": "number", "minimum": 0, "maximum": 1},
        "message": {"type": "string"},
        "size": {"type": "integer"},
        "format": {"type": "string"},
        "download_url": {"type": "string"},
        "error": {"type": "string"},
    },
}

KEY = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "prefix": {"type": "string"},
        "label": {"type": "string"},
        "owner_id": {"type": "integer"},
        "scopes": {"type": "array", "items": {"type": "string", "enum": list(SCOPES)}},
        "active": {"type": "boolean"},
        "created_at": {"type": "number"},
        "expires_at": {"type": ["number", "null"]},
        "last_used_at": {"type": ["number", "null"]},
        "uses": {"type": "integer"},
        "bytes": {"type": "integer"},
        "rate_limit": {"type": ["integer", "null"]},
    },
}


def _err(*codes: int) -> dict:
    return {
        str(code): {
            "description": "error envelope",
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
        }
        for code in codes
    }


def spec(request: web.Request) -> dict:
    base = _base(request)
    secured = [{"ApiKeyAuth": []}]
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "VYRON Music API",
            "version": "2.1",
            "summary": "Downloads, streaming, search, metadata, lyrics and keys for Telegram music bots.",
            "description": (
                "A production-grade music API served by the VYRON bot on the "
                "same URL as its Mini App. Authenticate with `X-API-Key` (or `Authorization: Bearer`). "
                "Every failure returns `{ok:false, error, code, request_id}`."
            ),
            "contact": {"name": "VYRON", "url": settings.git_repo},
            "license": {"name": "MIT"},
        },
        "servers": [{"url": base, "description": "this deployment"}],
        "tags": [
            {"name": "System", "description": "health, version and metrics"},
            {"name": "Tracks", "description": "download and stream audio"},
            {"name": "Discovery", "description": "search and metadata"},
            {"name": "Lyrics", "description": "LRCLIB lyrics"},
            {"name": "Keys", "description": "key introspection and administration"},
            {"name": "Sources", "description": "which services VYRON can play from, and their health"},
        ],
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                    "description": "A `vyrn_…` key minted in the Mini App (Music API) or with /getapi.",
                }
            },
            "schemas": {
                "DownloadJob": DOWNLOAD_JOB,
                "Track": TRACK,
                "Error": ERROR,
                "Key": KEY,
                "SearchResult": {
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "query": {"type": "string"},
                        "count": {"type": "integer"},
                        "took_ms": {"type": "number"},
                        "results": {"type": "array", "items": {"$ref": "#/components/schemas/Track"}},
                    },
                },
            },
            "parameters": {
                "VideoId": {
                    "name": "video_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string", "pattern": "^[A-Za-z0-9_-]{6,24}$"},
                }
            },
        },
        "security": secured,
        "paths": {
            "/health": {
                "get": {
                    "tags": ["System"],
                    "summary": "Liveness + readiness",
                    "security": [],
                    "responses": {
                        "200": {
                            "description": "service status",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }
                    },
                }
            },
            "/": {
                "get": {
                    "tags": ["System"],
                    "summary": "HTML docs page (or the JSON index with ?format=json)",
                    "security": [],
                    "responses": {"200": {"description": "docs or index"}},
                }
            },
            "/docs": {
                "get": {
                    "tags": ["System"],
                    "summary": "Human-readable documentation",
                    "security": [],
                    "responses": {"200": {"description": "HTML"}},
                }
            },
            "/openapi.json": {
                "get": {
                    "tags": ["System"],
                    "summary": "This document",
                    "security": [],
                    "responses": {"200": {"description": "OpenAPI 3.1"}},
                }
            },
            "/ready": {
                "get": {
                    "tags": ["System"],
                    "summary": "Readiness — 503 while the engine boots",
                    "description": (
                        "Use this for load balancers and uptime probes that should stop "
                        "sending traffic; use /health for liveness (it never restarts a "
                        "booting instance)."
                    ),
                    "security": [],
                    "responses": {"200": {"description": "ready"}, "503": {"description": "booting"}},
                }
            },
            "/version": {
                "get": {
                    "tags": ["System"],
                    "summary": "API and bot versions",
                    "security": [],
                    "responses": {"200": {"description": "versions"}},
                }
            },
            "/metrics": {
                "get": {
                    "tags": ["System"],
                    "summary": "Request, download and latency metrics",
                    "description": "Requires the `admin` scope. `?format=prometheus` returns Prometheus text.",
                    "parameters": [
                        {
                            "name": "format",
                            "in": "query",
                            "schema": {"type": "string", "enum": ["json", "prometheus"]},
                        }
                    ],
                    "responses": {"200": {"description": "metrics"}, **_err(403)},
                }
            },
            "/tracks": {
                "post": {
                    "tags": ["Tracks"],
                    "summary": "Download audio (by video id, URL or search query)",
                    "description": (
                        "Streams the MP3 back. Requires the `download` scope. "
                        "Supports HTTP Range, so clients can seek."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "video_id": {"type": "string"},
                                        "url": {"type": "string"},
                                        "query": {"type": "string"},
                                    },
                                    "anyOf": [{"required": ["video_id"]}, {"required": ["url"]}, {"required": ["query"]}],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {"description": "audio/mpeg", "content": {"audio/mpeg": {}}},
                        **_err(400, 401, 403, 429, 502, 503),
                    },
                }
            },
            "/tracks/{video_id}": {
                "get": {
                    "tags": ["Discovery"],
                    "summary": "Track metadata (no download)",
                    "parameters": [{"$ref": "#/components/parameters/VideoId"}],
                    "responses": {
                        "200": {
                            "description": "track",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"ok": {"type": "boolean"}, "track": {"$ref": "#/components/schemas/Track"}},
                                    }
                                }
                            },
                        },
                        **_err(400, 403, 429, 502),
                    },
                }
            },
            "/tracks/{video_id}/stream": {
                "get": {
                    "tags": ["Tracks"],
                    "summary": "Stream audio inline (Range supported)",
                    "parameters": [
                        {"$ref": "#/components/parameters/VideoId"},
                        {"name": "download", "in": "query", "schema": {"type": "boolean"}},
                    ],
                    "responses": {"200": {"description": "audio"}, **_err(400, 403, 429)},
                }
            },
            "/downloads": {
                "post": {
                    "tags": ["Downloads"],
                    "summary": "Submit an asynchronous download",
                    "description": (
                        "Same engine as `POST /tracks`, but it returns immediately with a "
                        "job id: poll `/downloads/{job_id}` for progress, then fetch "
                        "`/downloads/{job_id}/file`. Requires the `download` scope."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "video_id": {"type": "string"},
                                        "url": {"type": "string"},
                                        "query": {"type": "string"},
                                        "format": {"type": "string", "enum": ["audio", "video"]},
                                    },
                                    "anyOf": [
                                        {"required": ["video_id"]},
                                        {"required": ["url"]},
                                        {"required": ["query"]},
                                    ],
                                }
                            }
                        },
                    },
                    "responses": {
                        "202": {"description": "job accepted", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/DownloadJob"}}}},
                        **_err(400, 401, 403, 429, 502, 503),
                    },
                },
                "get": {
                    "tags": ["Downloads"],
                    "summary": "Recent jobs for the calling key",
                    "responses": {"200": {"description": "jobs"}, **_err(403, 429)},
                },
            },
            "/downloads/{job_id}": {
                "get": {
                    "tags": ["Downloads"],
                    "summary": "Poll a download job",
                    "parameters": [{"name": "job_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "job", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/DownloadJob"}}}},
                        **_err(403, 404, 429),
                    },
                },
                "delete": {
                    "tags": ["Downloads"],
                    "summary": "Cancel a job",
                    "parameters": [{"name": "job_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"202": {"description": "cancelled"}, **_err(403, 404, 429)},
                },
            },
            "/downloads/{job_id}/file": {
                "get": {
                    "tags": ["Downloads"],
                    "summary": "Fetch a finished file (Range supported)",
                    "parameters": [
                        {"name": "job_id", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "download", "in": "query", "schema": {"type": "boolean"}},
                    ],
                    "responses": {"200": {"description": "media"}, **_err(403, 404, 409, 429)},
                }
            },
            "/downloads/by-video-id/{video_id}": {
                "get": {
                    "tags": ["Tracks"],
                    "summary": "The newest job for a video id",
                    "responses": {"200": {"description": "job"}, **_err(404)},
                }
            },
            "/search": {
                "get": {
                    "tags": ["Discovery"],
                    "summary": "Search YouTube",
                    "parameters": [
                        {"name": "q", "in": "query", "required": True, "schema": {"type": "string"}},
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 25}},
                    ],
                    "responses": {
                        "200": {"description": "results", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/SearchResult"}}}},
                        **_err(400, 403, 429, 502),
                    },
                },
                "post": {
                    "tags": ["Discovery"],
                    "summary": "Search YouTube (JSON body)",
                    "responses": {"200": {"description": "results"}, **_err(400, 403, 429, 502)},
                },
            },
            "/lyrics": {
                "post": {
                    "tags": ["Lyrics"],
                    "summary": "Lyrics for a title/artist (JSON body)",
                    "responses": {"200": {"description": "lyrics"}, **_err(400)},
                },
                "get": {
                    "tags": ["Lyrics"],
                    "summary": "Lyrics from LRCLIB",
                    "parameters": [
                        {"name": "title", "in": "query", "required": True, "schema": {"type": "string"}},
                        {"name": "artist", "in": "query", "schema": {"type": "string"}},
                        {"name": "duration", "in": "query", "schema": {"type": "integer"}},
                    ],
                    "responses": {"200": {"description": "lyrics"}, **_err(400, 403, 404, 503)},
                }
            },
            "/me": {
                "get": {
                    "tags": ["Keys"],
                    "summary": "The calling key: scopes, capabilities, usage and expiry",
                    "description": (
                        "`capabilities` says exactly what this key may do, `usage` carries "
                        "request/byte counters and `expires_in` seconds until it stops working."
                    ),
                    "responses": {"200": {"description": "key info"}, **_err(403, 429)},
                }
            },
            "/sources": {
                "get": {
                    "tags": ["Sources"],
                    "summary": "Every playback source, in fallback order",
                    "description": (
                        "`primary` is what answers first, `fallback` is the direct-stream chain "
                        "used when YouTube returns nothing, and `sources[]` reports each entry's "
                        "live counters — successes, failures, average latency and the last error. "
                        "Counters survive restarts. `?probe=1` (admin scope) asks every stream "
                        "source for one track and returns the measured latency."
                    ),
                    "responses": {"200": {"description": "sources"}, **_err(401, 403)},
                }
            },
            "/sources/{name}": {
                "get": {
                    "tags": ["Sources"],
                    "summary": "One source's detail and health",
                    "parameters": [
                        {
                            "name": "name",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "enum": ["ytmusic", "ytdlp", "audius", "jiosaavn", "spotify", "deezer", "apple", "soundcloud"]},
                        }
                    ],
                    "responses": {"200": {"description": "source"}, **_err(403, 404)},
                }
            },
            "/admin/keys": {
                "get": {
                    "tags": ["Keys"],
                    "summary": "List every key (masked)",
                    "description": "Requires the `admin` scope.",
                    "responses": {"200": {"description": "keys"}, **_err(403)},
                },
                "post": {
                    "tags": ["Keys"],
                    "summary": "Mint a key",
                    "description": "Requires the `admin` scope. The raw key is returned exactly once.",
                    "responses": {"201": {"description": "created"}, **_err(400, 403)},
                },
            },
            "/admin/keys/{identifier}": {
                "get": {
                    "tags": ["Keys"],
                    "summary": "One key's details (masked, never the hash)",
                    "responses": {"200": {"description": "key"}, **_err(403, 404)},
                },
                "patch": {
                    "tags": ["Keys"],
                    "summary": "Edit a key without rotating it",
                    "description": (
                        "Change `label`, `scopes`, `days` (expiry; `0` = never) or `rate_limit` "
                        "(requests per minute; `0` = the deployment default). The secret stays "
                        "valid, so a client holding it keeps working."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string", "maxLength": 40},
                                        "scopes": {"type": "array", "items": {"type": "string"}},
                                        "days": {"type": "integer"},
                                        "rate_limit": {"type": "integer"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "updated"}, **_err(400, 403, 404)},
                },
                "delete": {
                    "tags": ["Keys"],
                    "summary": "Revoke a key by id or prefix",
                    "responses": {"200": {"description": "revoked"}, **_err(403, 404)},
                },
            },
            "/keys": {
                "get": {
                    "tags": ["Keys"],
                    "summary": "Your keys (self-service)",
                    "responses": {"200": {"description": "keys"}, **_err(403)},
                },
                "post": {
                    "tags": ["Keys"],
                    "summary": "Mint a key for your own account (needs the admin scope)",
                    "responses": {"201": {"description": "created"}, **_err(400, 403)},
                },
            },
            "/keys/{identifier}": {
                "patch": {
                    "tags": ["Keys"],
                    "summary": "Edit one of your keys without rotating it",
                    "responses": {"200": {"description": "updated"}, **_err(400, 403, 404)},
                },
                "delete": {
                    "tags": ["Keys"],
                    "summary": "Revoke one of your keys",
                    "responses": {"200": {"description": "revoked"}, **_err(403, 404)},
                },
            },
            "/admin/keys/{identifier}/rotate": {
                "post": {
                    "tags": ["Keys"],
                    "summary": "Replace a key; the old secret stops working immediately",
                    "responses": {"200": {"description": "created"}, **_err(403, 404)},
                }
            },
            # ── legacy aliases (old clients keep working) ──────────────────
            "/track/by-video-id": {
                "get": {
                    "tags": ["Tracks"],
                    "summary": "Legacy alias for POST /tracks (query string)",
                    "deprecated": True,
                    "responses": {"200": {"description": "audio/mpeg"}, **_err(400, 401, 403, 429)},
                },
                "post": {
                    "tags": ["Tracks"],
                    "summary": "Legacy alias for POST /tracks",
                    "deprecated": True,
                    "responses": {"200": {"description": "audio/mpeg"}, **_err(400, 401, 403, 429)},
                }
            },
            "/track/by-query": {
                "get": {
                    "tags": ["Tracks"],
                    "summary": "Legacy alias for POST /tracks (query)",
                    "deprecated": True,
                    "responses": {"200": {"description": "audio/mpeg"}, **_err(400, 401, 403, 429)},
                },
                "post": {
                    "tags": ["Tracks"],
                    "summary": "Legacy alias for POST /tracks (query)",
                    "deprecated": True,
                    "responses": {"200": {"description": "audio/mpeg"}, **_err(400, 401, 403, 429)},
                }
            },
            "/info/by-video-id": {
                "get": {
                    "tags": ["Discovery"],
                    "summary": "Legacy alias for GET /tracks/{video_id}",
                    "deprecated": True,
                    "responses": {"200": {"description": "track"}, **_err(400, 403)},
                }
            },
            "/key": {
                "get": {
                    "tags": ["Keys"],
                    "summary": "Legacy alias for GET /me",
                    "deprecated": True,
                    "responses": {"200": {"description": "key info"}, **_err(403)},
                }
            },
        },
    }


__all__ = ["spec"]
