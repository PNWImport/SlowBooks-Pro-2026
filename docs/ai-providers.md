# AI Insights providers

Configure AI under **Settings → AI Insights**. The eight options are xAI Grok,
Groq, Cloudflare Workers AI, Cloudflare Worker Gateway, Anthropic Claude,
OpenAI, Google Gemini, and **Custom (OpenAI-compatible)**.

## Models and custom endpoints

Every provider has curated model choices plus **Custom…**. A manual model ID is
stored and sent unchanged, so vendor renames do not require a Slowbooks update.
The generic Custom provider requires a non-empty model ID.

Bundled choices were reviewed September 7, 2026 against the official
[xAI](https://docs.x.ai/developers/models),
[Groq](https://console.groq.com/docs/models),
[Cloudflare](https://developers.cloudflare.com/workers-ai/models/),
[Anthropic](https://platform.claude.com/docs/en/about-claude/model-deprecations),
[OpenAI](https://developers.openai.com/api/docs/models/gpt), and
[Gemini](https://ai.google.dev/gemini-api/docs/models) catalogues.

- Enter the provider's model ID and API key, plus its public HTTPS base URL
  (for example, `https://api.example.com/v1`).
- SlowBooks appends `/chat/completions` unless already present. Include any
  provider-required prefix such as `/v1`; SlowBooks does not discover it.
- This adapter uses Chat Completions, not the Responses API or a ChatGPT login.
  Text responses must use `choices[].message.content`; tool-based Q&A also
  requires compatible function/tool calls. Check the endpoint's model support.
- Localhost, LAN/private addresses, embedded URL credentials, and plain HTTP
  are deliberately refused. The connection is pinned to the checked public DNS
  answer, redirects are disabled, and TLS verification stays on. Do not expose
  an unsecured local model just to bypass these restrictions.

The distinction between messages, responses, and tools follows the
[OpenAI Chat Completions reference](https://developers.openai.com/api/reference/cli/resources/chat/subresources/completions).

## Save, test, and data sharing

**Save** stores configuration. Leaving the UI key field blank preserves the key;
**Remove** clears it. API clients must omit `api_key` to preserve it—an explicit
empty string removes it. `endpoint_url` is accepted and returned by `ai-config`;
the raw API key is never returned.

**Test** first saves the form, then makes a small external request. Insights,
predefined analyses, and Q&A send relevant business data to the selected service;
this can include customer names and financial figures. Review the provider's
data handling and your authorization before using real books. Offline analytics
do not require an AI provider.

Keys are encrypted at rest. Back up the settings encryption key as well as the
database. Docker Compose requires a stable `SETTINGS_ENCRYPTION_KEY` from
`.env`; keep that file securely backed up. Native installs must preserve
`.slowbooks-master.key`. Losing either key source makes stored credentials
unrecoverable.

## Validation limits

The dropdown is a bundled list, not live discovery. Verify account access,
supported parameters, pricing, and limits with the provider. Mock tests cover
all adapters and configuration wiring but cannot certify third-party service
availability. Use **Test** with your authorized endpoint before an analysis.
