# Security

[Previous](admin_guide) | [Next](mcp_guide) | [Index](index)

This guide documents security behavior currently implemented in Adapt.

## Authentication

Adapt supports:

1. Session cookie authentication (`adapt_session`)
2. API key authentication (`X-API-Key`)

Login/logout routes:

- `GET /auth/login`
- `POST /auth/login`
- `POST /auth/logout`

Session behavior:

- Session TTL is 7 days
- Sliding renewal on valid session usage
- Expired sessions are cleaned by a background task

API key behavior:

- Keys are stored as SHA-256 hashes
- Keys can be inactive or expired
- `last_used_at` is updated on successful key usage

The MCP interface (`/mcp/`, see the [MCP Guide](mcp_guide)) uses the same
authentication resolver as HTTP routes, so tool calls accept either a
session cookie or an API key. API keys are the supported and recommended MCP
client mechanism. Authentication is enforced when a tool executes, not
during initialization or tool discovery. Cookie-authenticated MCP requests
are still subject to CSRF validation because the transport uses HTTP POST.

## Authorization

Adapt enforces resource permissions through users, groups, and permissions.

- Superusers bypass standard permission checks
- Generated resource routes are mounted with permission dependencies
- `read` is required for GET
- `write` is required for POST/PATCH/DELETE

## Password Security

Password handling:

- PBKDF2-HMAC-SHA256
- 100,000 iterations
- Per-user random salt
- Constant-time comparison for verification

## CSRF Protection

CSRF is enforced for unsafe HTTP methods when session cookies are involved.

Key points:

- CSRF cookie name: `adapt_csrf`
- CSRF header name: `X-CSRF-Token`
- Form field fallback: `csrf_token`
- API-key-only requests without session cookies are exempt
- If both session and API key are present, CSRF still applies

For example, log in and store the session and CSRF cookies in a curl cookie
jar. Then copy the CSRF cookie into the header for an unsafe request:

```bash
curl -c /tmp/adapt-cookies.txt -X POST \
  --data-urlencode "username=admin" \
  --data-urlencode "password=<password>" \
  http://localhost:8000/auth/login

CSRF_TOKEN=$(awk '$6 == "adapt_csrf" {print $7}' /tmp/adapt-cookies.txt)
curl -b /tmp/adapt-cookies.txt -X POST \
  -H "X-CSRF-Token: $CSRF_TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/products/ \
  -d '{"action":"create","data":[{"name":"Keyboard"}]}'
```

For command-line mutations, an API-key-only request is simpler and does not
require CSRF handling.

## Security Headers

Adapt sets security headers on responses:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Content-Security-Policy: ...` (policy configured in code)
- `Strict-Transport-Security` when TLS is enabled

## Host Header Protection

Adapt uses `TrustedHostMiddleware` with allowed hosts derived from configured host.

## TLS and Cookies

When TLS cert and key are configured together:

- HTTPS is enabled
- HSTS is enabled
- Secure-cookie behavior is enabled by server configuration

## Locking and Safe Writes

Dataset write paths use lock management and atomic replacement to reduce corruption and race risks.

Lock behavior includes:

- Per-resource lock records
- Retry with exponential backoff
- Timeout-based acquisition failure
- Stale lock cleanup

## Audit and Admin Security Endpoints

Superuser endpoints include:

- `/admin/users`
- `/admin/groups`
- `/admin/permissions`
- `/admin/locks`
- `/admin/cache`
- `/admin/api-keys`
- `/admin/audit-logs`

## Practical Checks

```bash
# Current user
curl -H "X-API-Key: <key>" http://localhost:8000/auth/me

# Audit logs (superuser)
curl -H "X-API-Key: <superuser-key>" http://localhost:8000/admin/audit-logs

# Health
curl http://localhost:8000/health
```

## Recommendations

- Always use TLS in non-local environments.
- Rotate API keys and deactivate unused keys.
- Keep superuser accounts limited and monitored.
- Review audit logs regularly.

[Previous](admin_guide) | [Next](mcp_guide) | [Index](index)
