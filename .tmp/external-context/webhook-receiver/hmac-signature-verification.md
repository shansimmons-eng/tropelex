---
source: Official docs + community patterns
library: webhook-security
topic: HMAC-SHA256 signature verification
fetched: 2026-07-16T00:00:00Z
official_docs:
  - https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
  - https://docs.gitlab.com/user/project/integrations/webhooks/
---

# HMAC-SHA256 Signature Verification Patterns

## Core Pattern

All HMAC webhook verification follows the same flow:
1. Provider computes `HMAC-SHA256(secret, raw_body)`
2. Provider sends signature in HTTP header
3. Receiver recomputes HMAC and compares using **constant-time comparison**
4. Any mismatch → reject immediately (HTTP 401/403)

## GitHub Webhooks

### Headers
- `X-Hub-Signature-256` — HMAC-SHA256 hex digest prefixed with `sha256=`
- `X-GitHub-Event` — event type (e.g., `push`, `ping`)
- `X-GitHub-Delivery` — unique delivery ID (use for idempotency)
- `X-GitHub-Hook-ID` — webhook hook ID

### Signature Format
```
sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17
```

### Verification Steps
1. Read raw body bytes (BEFORE any JSON parsing)
2. Extract signature from `X-Hub-Signature-256` header
3. Strip `sha256=` prefix
4. Compute `HMAC-SHA256(webhook_secret, raw_body)`
5. Compare hex digests using constant-time comparison

### Python Implementation
```python
import hashlib
import hmac
from fastapi import Request, HTTPException

async def verify_github_signature(request: Request) -> dict:
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        raise HTTPException(status_code=403, detail="Missing signature header")

    raw_body = await request.body()  # raw bytes, NOT parsed JSON

    # GitHub prefixes with "sha256="
    if not signature_header.startswith("sha256="):
        raise HTTPException(status_code=400, detail="Invalid signature format")
    sig_value = signature_header.removeprefix("sha256=")

    # Compute expected HMAC
    secret = os.environ["GITHUB_WEBHOOK_SECRET"]
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    # Constant-time comparison (CRITICAL — prevents timing attacks)
    if not hmac.compare_digest(sig_value, expected):
        raise HTTPException(status_code=403, detail="Invalid signature")

    return json.loads(raw_body)
```

### Node.js/TypeScript Implementation
```javascript
const crypto = require('crypto');

function verifyGitHubSignature(payload, signatureHeader, secret) {
  // Strip "sha256=" prefix
  const receivedSig = signatureHeader.replace(/^sha256=/, '');

  // Compute HMAC
  const expectedSig = crypto
    .createHmac('sha256', secret)
    .update(payload)
    .digest('hex');

  // Constant-time comparison
  return crypto.timingSafeEqual(
    Buffer.from(receivedSig, 'hex'),
    Buffer.from(expectedSig, 'hex')
  );
}

// In handler:
const signature = req.headers['x-hub-signature-256'];
const rawBody = req.rawBody; // Must be raw bytes!
const secret = process.env.GITHUB_WEBHOOK_SECRET;

if (!verifyGitHubSignature(rawBody, signature, secret)) {
  return res.status(401).send('Unauthorized');
}
```

### Using @octokit/webhooks (TypeScript)
```typescript
import { Webhooks } from "@octokit/webhooks";

const webhooks = new Webhooks({ secret: process.env.WEBHOOK_SECRET });

const handleWebhook = async (req, res) => {
  const signature = req.headers["x-hub-signature-256"];
  const body = await req.text();

  if (!(await webhooks.verify(body, signature))) {
    res.status(401).send("Unauthorized");
    return;
  }
  // Process valid webhook...
};
```

## GitLab Webhooks

GitLab supports two authentication methods:

### Method 1: Signing Token (Recommended — GitLab 19.0+)
Follows the [Standard Webhooks](https://www.standardwebhooks.com/) specification.

#### Headers
- `webhook-id` — unique message ID (same across retries)
- `webhook-timestamp` — Unix timestamp
- `webhook-signature` — space-separated list of `v1,{base64_signature}` values

#### Signature Computation
The signed message is: `{message_id}.{timestamp}.{body}`

#### Python Verification
```python
import base64
import hashlib
import hmac
import time

def verify_gitlab_signing_token(
    signing_token: str,
    message_id: str,
    timestamp: str,
    body: bytes,
    received_signatures: str,
    max_age_seconds: int = 300  # 5 minutes
) -> bool:
    # 1. Check timestamp freshness (replay protection)
    if abs(time.time() - int(timestamp)) > max_age_seconds:
        return False

    # 2. Decode signing key (strip "whsec_" prefix, base64 decode)
    raw_key = base64.b64decode(signing_token.removeprefix("whsec_"))

    # 3. Construct message
    message = f"{message_id}.{timestamp}.{body}".encode("utf-8")

    # 4. Compute HMAC-SHA256
    digest = hmac.new(raw_key, message, hashlib.sha256).digest()

    # 5. Encode as base64 with "v1," prefix
    expected = "v1," + base64.b64encode(digest).decode("utf-8")

    # 6. Check against all received signatures (space-separated)
    return any(
        hmac.compare_digest(expected, sig)
        for sig in received_signatures.split(" ")
    )

# Usage in handler:
def handle_gitlab_webhook(request):
    body = request.body
    sig = request.headers.get("webhook-signature", "")
    msg_id = request.headers.get("webhook-id", "")
    timestamp = request.headers.get("webhook-timestamp", "")

    if not verify_gitlab_signing_token(
        os.environ["GITLAB_SIGNING_TOKEN"],
        msg_id, timestamp, body, sig
    ):
        raise HTTPException(status_code=403, detail="Invalid signature")
```

### Method 2: Secret Token (Legacy — NOT recommended)
Sends plaintext in `X-Gitlab-Token` header. Weak — no payload integrity check.
```python
token = request.headers.get("X-Gitlab-Token")
if token != os.environ["GITLAB_SECRET_TOKEN"]:
    raise HTTPException(status_code=403, detail="Invalid token")
```

## Critical Rules

1. **ALWAYS use the RAW body** — never parse JSON before verification
2. **ALWAYS use constant-time comparison** — `hmac.compare_digest()` or `crypto.timingSafeEqual()`
3. **NEVER use `==`** for signature comparison — vulnerable to timing attacks
4. **Handle UTF-8 encoding** — webhook payloads may contain unicode
5. **Check proxies/load balancers** — they may modify headers or body before verification
6. **Handle ping events** — GitHub sends `ping` on webhook setup; return 200 OK immediately
7. **Store secrets in env vars** — never hardcode or commit to repos

## Test Vectors (GitHub)
- Secret: `It's a Secret to Everybody`
- Payload: `Hello, World!`
- Expected signature: `757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17`
- X-Hub-Signature-256: `sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17`
