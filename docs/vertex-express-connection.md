# Connecting to Google image models (Vertex AI Express) — language-agnostic reference

How this project calls Gemini/Imagen image models with plain HTTPS + JSON.
No SDK required — works from Python, TypeScript, curl, anything.
Verified 2026-07-05 against project `curios-vertex`.

## 1. The three transports (and which one we use)

| Transport | Host | Auth header | When |
|---|---|---|---|
| **Vertex Express** ✅ (ours) | `aiplatform.googleapis.com` | `x-goog-api-key: <AQ. key>` | API key created in a GCP project ("AQ." prefix). Billed to that project's credits. |
| Vertex (service account) | `{loc}-aiplatform.googleapis.com` or `aiplatform.googleapis.com` (global) | `Authorization: Bearer <OAuth2 token>` | Server deployments with a service-account JSON (role: Vertex AI User). |
| AI Studio | `generativelanguage.googleapis.com` | `x-goog-api-key: <AIza key>` | Hobby keys. **Free tier has ZERO image-model quota** (429 `limit: 0`). |

⚠️ Keys are transport-locked: our `AQ.` express key returns **403 on AI Studio**, and
`AIza` AI Studio keys don't work on `aiplatform`. Don't mix them.

## 2. Image *editing* — Gemini (Nano Banana 2 Lite)

Model: `gemini-3.1-flash-lite-image` · ~$0.034/image · ~4–8 s

```
POST https://aiplatform.googleapis.com/v1/publishers/google/models/gemini-3.1-flash-lite-image:generateContent
x-goog-api-key: <KEY>
Content-Type: application/json
```

```json
{
  "contents": [{
    "role": "user",
    "parts": [
      { "inline_data": { "mime_type": "image/jpeg", "data": "<base64 of input photo>" } },
      { "text": "Rotate this person's head: three-quarter turn to the left. Same person, identical facial features..." }
    ]
  }],
  "generationConfig": { "responseModalities": ["IMAGE"] }
}
```

Response — find the first image part (fields come back **camelCase**):

```json
{ "candidates": [ { "content": { "parts": [
  { "inlineData": { "mimeType": "image/png", "data": "<base64>" } }
] } } ] }
```

TypeScript sketch:

```ts
const res = await fetch(URL, {
  method: "POST",
  headers: { "x-goog-api-key": KEY, "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});
if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
const data = await res.json();
const part = data.candidates?.[0]?.content?.parts?.find((p: any) => p.inlineData);
const imageBytes = Buffer.from(part.inlineData.data, "base64");
```

## 3. Text-to-image — Imagen 4 Fast

Model: `imagen-4.0-fast-generate-001` · ~$0.02/image · **no input image supported**
(generation only — cannot preserve a person's identity; unusable for multiview).

```
POST https://aiplatform.googleapis.com/v1/publishers/google/models/imagen-4.0-fast-generate-001:predict
```

```json
{ "instances": [{ "prompt": "a friendly robot character, 3d render" }],
  "parameters": { "sampleCount": 1, "aspectRatio": "1:1" } }
```

Response: `predictions[0].bytesBase64Encoded`.

## 4. Gotchas we hit (save yourself the debugging)

- **`"role": "user"` is mandatory on Vertex** (400 "Please use a valid role" without it). AI Studio accepts it too — always include it.
- **429 with `limit: 0` in the body** = the key's tier has no quota for that model (not a rate limit — retrying is useless). Other 429s are transient: retry once after ~2 s.
- **404** = model not available on that endpoint/location. Image models live on the **global** endpoint; regional hosts (`us-central1-aiplatform...`) may 404.
- Request JSON accepts `inline_data`/`inlineData` interchangeably; **responses are always camelCase**.
- The model may return 200 with a text part and *no image* (rare refusals) — treat "no image part" as a failure case.
- Use a ~30 s timeout; Lite typically answers in <8 s.
- Fire requests concurrently (8 parallel is fine on paid/express tier) — this is what takes our 8-view generation to ~customer-visible 5–10 s.

## 5. Service-account variant (if you ever need it)

Exchange the JSON key for an OAuth2 token (scope `https://www.googleapis.com/auth/cloud-platform`
— any Google auth lib does this), then:

```
POST https://aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/global/publishers/google/models/{MODEL}:generateContent
Authorization: Bearer <token>
```

Same request/response bodies as §2. Tokens last ~1 h — cache and refresh.

## 6. Where this lives in our code

- Transport selection + auth: `backend/app/pipeline/multiview_generator.py` → `gemini_endpoint()`
- The edit call: same file → `gemini_edit()`
- Config: `backend/.env` → `GCP_PROJECT_ID`, `GCP_LOCATION`, `GEMINI_API_KEY`, optional `GOOGLE_APPLICATION_CREDENTIALS`
