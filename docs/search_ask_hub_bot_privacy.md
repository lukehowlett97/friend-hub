# Search Ask Hub Bot Privacy Notes

The Search page Ask Hub Bot feature is read-only. It sends the configured AI
provider only the user's question plus a capped set of validated search-result
titles, snippets, metadata, and source IDs.

It does not send full chat history by default, raw database rows, hidden server
context, write tools, memories, suggestions, draft actions, pins, or message
creation capability.

Provider and model are controlled by the existing backend AI settings:

- `AI_LAB_PROVIDER`: `fake`, `ollama`, or `openrouter`
- `AI_API_PROVIDER`: provider used by the OpenRouter-compatible gateway
- `AI_DEFAULT_CHAT_MODEL`: model name sent to the provider

If `openrouter` is used, validated snippets leave the Friend Hub server and are
sent to OpenRouter for completion. Review OpenRouter's current retention and
privacy controls for the configured account, and disable provider-side logging
or training where the provider supports it. With `ollama`, snippets are sent to
the configured local Ollama server. With `fake`, no external provider is called.

Search result text is treated as untrusted content in the prompt. The model is
asked to return only JSON with an answer and source IDs; the backend maps those
source IDs back to server-validated sources and discards invented references.
