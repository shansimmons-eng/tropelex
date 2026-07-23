# API Keys

Tropelex uses environment variables for API keys. Keys are never committed to the repository.

---

## OpenAI API Key

**Required for AI-powered prompt compression.**

The compression feature sends prompts to `gpt-4o-mini` to strip filler, fix typos, and rewrite prompts as concise imperatives. Without this key, compression falls back to dictionary-based rules only.

### Setup

**Option 1 — `.env` file (recommended):**
```bash
# Create .env in the project root
echo 'OPENAI_API_KEY=sk-your-key-here' > .env
```

**Option 2 — Environment variable:**
```bash
export OPENAI_API_KEY=sk-your-key-here
```

**Option 3 — Via the Settings UI:**
Open http://localhost:8766, go to **Settings → API Keys**, paste your key and click **Save Settings**. The key is written to `.env` and applied immediately without a server restart.

### Getting a key
1. Go to https://platform.openai.com/api-keys
2. Create a new secret key
3. Copy the `sk-...` value — it's only shown once

### Cost
Compression uses `gpt-4o-mini` which is extremely cheap (~$0.00015 per prompt). A thousand compressions costs less than $0.15.

---

## Brave Search API Key

**Optional — enhances web research in Tropebook.**

Without this key, Tropebook falls back to DuckDuckGo (free, no key needed, but rate-limited).

### Setup

```bash
# .env file
BRAVE_SEARCH_API_KEY=your-brave-key-here

# Or environment
export BRAVE_SEARCH_API_KEY=your-brave-key-here
```

### Getting a key
1. Go to https://api.search.brave.com/
2. Sign up for a free or paid plan
3. Copy your API key

### Free tier limits
The Brave free tier allows ~2,000 queries/month, which is more than enough for typical research use.

---

## Deep Research Sources (last30days engine)

**Optional — expands Deep Research coverage.**

The Deep Research feature uses the last30days engine to search Reddit, X, YouTube, GitHub, HackerNews, Polymarket, and web grounding. Some sources require API keys; others work without any. The engine degrades gracefully — missing sources are skipped.

### xAI API Key

Enables X/Twitter search and doubles as the LLM planner for the engine's query planning. Also used for the Deep Research synthesis step (writing the narrative brief).

```bash
# .env file
XAI_API_KEY=xai-your-key-here
```

**Getting a key:**
1. Go to https://console.x.ai/
2. Create an API key
3. Free tier includes generous credits

### ScrapeCreators API Key

One key unlocks five sources: Reddit (without 403 rate limits), TikTok, Instagram, Threads, and Pinterest. 10,000 free calls.

```bash
# .env file
SCRAPECREATORS_API_KEY=scrt-your-key-here
```

**Getting a key:**
1. Go to https://scrapecreators.com/
2. Sign up for a free account (10,000 calls)
3. Copy your API key

### Bluesky

Requires both a handle and an app password.

```bash
# .env file
BSKY_HANDLE=your-handle.bsky.social
BSKY_APP_PASSWORD=your-app-password
```

**Getting credentials:**
1. Go to https://bsky.app/settings/app-passwords
2. Create a new app password
3. Copy both your handle and the password

### X/Twitter Cookies (alternative to xAI)

If you don't have an xAI key, you can use browser cookies from x.com instead.

```bash
# .env file
AUTH_TOKEN=your-auth-token
CT0=your-ct0-token
```

**Getting cookies:**
1. Log into x.com in your browser
2. Open DevTools → Application → Cookies
3. Copy `auth_token` and `ct0` values

### Parallel AI

LLM-optimized web search results.

```bash
# .env file
PARALLEL_API_KEY=your-parallel-key
```

### Free sources (no keys needed)

These sources work without any configuration:
- **HackerNews** — Algolia API (free)
- **GitHub** — public API (free, rate-limited)
- **Polymarket** — Gamma API (free)
- **YouTube** — via yt-dlp (free, must be installed)
- **Reddit** — keyless RSS tiers (limited, may return 403s)

---

## Security

- **Never commit `.env` to git** — it's in `.gitignore`
- Keys written via the Settings UI go only to your local `.env` file
- The server only accepts keys for explicitly whitelisted names: `OPENAI_API_KEY`, `BRAVE_SEARCH_API_KEY`, `ANTHROPIC_API_KEY`, `EXA_API_KEY`, `SERPER_API_KEY`, `XAI_API_KEY`, `SCRAPECREATORS_API_KEY`, `BSKY_HANDLE`, `BSKY_APP_PASSWORD`, `AUTH_TOKEN`, `CT0`, `PARALLEL_API_KEY`
- All secret keys are masked in `GET /api/settings` responses
- The server binds to `127.0.0.1` only — not accessible from other machines on your network
- CORS is restricted to `localhost:8766`

---

## Checking if keys are working

Visit **Settings → API Keys → Test** in the UI, or:

```bash
curl -s -X POST http://localhost:8766/api/compress \
  -H "Content-Type: application/json" \
  -d '{"prompt": "could you please help me write a function"}'
```

A working response looks like:
```json
{"compressed": "Write a function", "model": "gpt-4o-mini", "saved_pct": 62.5}
```

An error response:
```json
{"error": "No valid OpenAI API key configured", "compressed": "could you please..."}
```
