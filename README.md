# Article Extractor Service

A lightweight HTTP microservice that accepts a URL, fetches its HTML, extracts the main article content using Readability, and returns clean plain text. Designed to run as a Docker container on a homelab server and be called from n8n workflows.

## Running locally

```bash
docker compose up --build
```

The service will be available at `http://localhost:8080`.

## API

### `GET /extract?url=<url>`

Fetches and extracts article content from the given URL.

**Response:**
```json
{
  "url": "https://example.com/article",
  "title": "Article Title",
  "text": "Plain text body of the article...",
  "error": null
}
```

On failure (unreachable URL, timeout, unsupported content type), the service still returns HTTP 200 with `error` populated and `text`/`title` as `null`.

**Example:**
```bash
curl "http://localhost:8080/extract?url=https://example.com/some-article"
```

### `GET /health`

Returns `{"status": "ok"}`. Use this for Docker health checks or to verify the service is reachable before a workflow runs.

## Configuration (`.env`)

| Variable          | Default | Description                              |
|-------------------|---------|------------------------------------------|
| `PORT`            | `8080`  | Port the service listens on              |
| `MAX_TEXT_LENGTH` | `4000`  | Max characters returned in `text` field  |
| `REQUEST_TIMEOUT` | `15`    | Seconds before a fetch times out         |

## Wiring into n8n

1. Use an **HTTP Request** node with method `GET` and URL:
   ```
   http://<HOST_LAN_IP>:8080/extract?url={{$json.link}}
   ```
   Use the LAN IP (e.g. `192.168.1.x`) rather than a hostname — n8n runs inside Docker and may not resolve hostnames on the host network.

2. The `text` field from the response is what you pass into your Claude API prompt.

3. Add a **Wait** node (2–3 seconds) between items when processing a list of URLs to avoid hammering target sites.

4. Optionally, add an **IF** node to check `error != null` and route failures to a separate branch.
