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

## Security

- **Never commit `.env` to git** — it's in `.gitignore`
- Keys written via the Settings UI go only to your local `.env` file
- The server only accepts keys for explicitly whitelisted names (`OPENAI_API_KEY`, `BRAVE_SEARCH_API_KEY`, `ANTHROPIC_API_KEY`)
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
