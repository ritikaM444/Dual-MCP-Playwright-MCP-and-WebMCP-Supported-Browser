# Running the agent through OmniRoute

**Why.** Gemini's free tier allows roughly 20 requests/day on full Flash
models, and one agent task spends one request *per step*. A complex task in
front of an examiner can exhaust that mid-demo. OmniRoute is a local,
MIT-licensed gateway that presents one OpenAI-compatible endpoint and fans
out across many free providers, falling back automatically when one runs out
of quota — so the rate limit stops being a single point of failure.

## Setup

OmniRoute is a Node program (the agent stays pure Python — this is a separate
service you run alongside it, like a database).

```bash
node -v          # need v20+; if missing: sudo apt install nodejs npm
npm install -g omniroute
omniroute        # starts on http://localhost:20128
```

Verify it answers before touching the agent:

```bash
curl http://localhost:20128/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Say OK"}]}'
```

If that returns a reply, you're set. In `.env`:

```
LLM_PROVIDER=omniroute
```

Then run the agent as usual. The UI header will show `provider: omniroute`.

## If it misbehaves on demo day

One word in `.env`:

```
LLM_PROVIDER=gemini
```

That's the whole rollback — same agent, same controller, same engines, back on
the path you've already proven. Keep `GEMINI_API_KEY` filled in so this always
works. **Test the fallback switch once before the review** so you know it's
instant.

## Honest status

This integration was written against OmniRoute's documented OpenAI-compatible
API and verified with a stubbed SDK (correct message sequence, tool-call
payload shape, multi-step loop) — but it has **not** been run against a live
OmniRoute instance. First real run is yours. Budget an hour, and keep the
Gemini fallback ready.
