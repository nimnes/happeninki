"""Provider wire formats shared by the bot's editorial operations.

No network calls here: transports retain their own timeouts and retry policies.
The internal response envelope is {message: {content: text}, done_reason: ...}.
"""
from urllib.parse import quote


def build_request(provider, url, key, payload):
    if provider not in {"google", "ollama"}:
        raise ValueError("LLM_PROVIDER must be google or ollama")
    if not key and provider == "google":
        raise ValueError("Set GOOGLE_API_KEY before using Google")
    if provider == "ollama":
        url = url.rstrip("/")
        if not url.endswith("/chat"):
            url += "/chat"
        return url, {"Authorization": f"Bearer {key}"}, payload

    model = payload["model"].removeprefix("models/")
    url = f"{url.rstrip('/')}/models/{quote(model, safe='')}:generateContent"
    # Prompts specify JSON; retain local validation rather than depend on
    # structured-output support varying between hosted Gemma versions.
    body = {
        "contents": [{"role": "model" if m["role"] == "assistant" else "user",
                      "parts": [{"text": m["content"]}]}
                     for m in payload["messages"] if m["role"] != "system"],
        "generationConfig": {
            "temperature": payload.get("options", {}).get("temperature", 0),
            "thinkingConfig": {"thinkingLevel": "minimal"},
        },
    }
    instructions = "\n\n".join(m["content"] for m in payload["messages"] if m["role"] == "system")
    if instructions:
        body["systemInstruction"] = {"parts": [{"text": instructions}]}
    if payload.get("options", {}).get("num_predict"):
        body["generationConfig"]["maxOutputTokens"] = payload["options"]["num_predict"]
    return url, {"x-goog-api-key": key}, body


def normalize_response(provider, response):
    if provider == "ollama":
        return response
    candidates = (response.get("candidates") or []) if isinstance(response, dict) else []
    if not candidates:
        return {"message": {"content": ""}, "done_reason": "blocked"}
    candidate = candidates[0]
    reason = candidate.get("finishReason")
    # Never accept truncated or safety-blocked content as a finished result.
    content = "".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", [])
                      if not p.get("thought")) if reason == "STOP" else ""
    return {"message": {"content": content},
            "done_reason": {"STOP": "stop", "MAX_TOKENS": "length"}.get(reason, "blocked")}
