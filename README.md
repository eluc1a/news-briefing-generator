# Article Extractor Service

A lightweight HTTP microservice that accepts a URL, fetches its HTML, extracts the main article content using Readability, and returns clean plain text. Runs as a Docker container on the `fox` homelab server and is called from n8n workflows.

## Current deployment

- **Host:** `fox` (LAN IP `192.168.0.89`)
- **Host port:** `8090` (container port `8080`)
- **Base URL:** `http://192.168.0.89:8090`
- **Container:** `jina-clone-extractor-1` (managed via `docker compose` in this directory)

`fox` already runs nginx on host port 8080, so the container is mapped to host port 8090.

## Deploying

From this directory on `fox`:

```bash
docker compose up -d --build
```

- `-d` detaches so it keeps running after you close the shell.
- `--build` rebuilds the image if any source file changed. Safe to run repeatedly.
- `restart: always` is set in `docker-compose.yml`, so the container comes back up after reboots or crashes.

### First-time build note

If `pip install` fails with DNS errors during build (seen in environments where Docker's default bridge can't resolve DNS), the compose file already pins the build network to `host` via:

```yaml
build:
  context: .
  network: host
```

No action needed — this is already configured.

Verify it's up:

```bash
curl http://192.168.0.89:8090/health
# → {"status":"ok"}
```

## Maintaining the deployment

### Check status
```bash
docker compose ps
```

### Tail logs
```bash
docker compose logs -f extractor
```

### Restart (e.g. after editing `.env`)
```bash
docker compose restart extractor
```

### Rebuild after code change
```bash
docker compose up -d --build
```

### Stop / start
```bash
docker compose stop extractor
docker compose start extractor
```

### Full teardown (removes container, keeps image)
```bash
docker compose down
```

### Update dependencies
Edit `requirements.txt`, then rebuild:
```bash
docker compose up -d --build
```

### Change host port
Edit the `ports:` line in `docker-compose.yml` (left side is host, right side is container — leave the right side as `8080`), then:
```bash
docker compose up -d
```

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

On failure (unreachable URL, timeout, unsupported content type), the service still returns HTTP 200 with `error` populated and `text`/`title` as `null`. This prevents n8n from treating transient fetch failures as workflow errors.

**Example:**
```bash
curl "http://192.168.0.89:8090/extract?url=https://example.com/some-article"
```

### `GET /health`

Returns `{"status": "ok"}`. Use this for Docker health checks or to verify the service is reachable before a workflow runs.

## Configuration (`.env`)

| Variable          | Default | Description                              |
|-------------------|---------|------------------------------------------|
| `PORT`            | `8080`  | Port the service listens on **inside the container** |
| `MAX_TEXT_LENGTH` | `4000`  | Max characters returned in `text` field  |
| `REQUEST_TIMEOUT` | `15`    | Seconds before a fetch times out         |

To change `MAX_TEXT_LENGTH` or `REQUEST_TIMEOUT`, edit `.env` and run `docker compose restart extractor`. Do not change `PORT` here unless you also update the container side of the `ports:` mapping in `docker-compose.yml`.

## Wiring into n8n

1. Use an **HTTP Request** node with method `GET` and URL:
   ```
   http://192.168.0.89:8090/extract?url={{$json.link}}
   ```
   Use the LAN IP rather than `fox` — n8n runs inside Docker and may not resolve hostnames on the host network.

2. The `text` field from the response is what you pass into your Claude API prompt.

3. Add a **Wait** node (2–3 seconds) between items when processing a list of URLs to avoid hammering target sites.

4. Optionally, add an **IF** node to check `error != null` and route failures to a separate branch.

## Troubleshooting

**`curl` to `/health` hangs or refuses connection**
- Check the container is running: `docker compose ps`
- Check logs for a crash loop: `docker compose logs extractor`

**Every request returns `{"error": "..."}`**
- DNS or network: verify the container can reach the internet: `docker compose exec extractor python -c "import httpx; print(httpx.get('https://example.com').status_code)"`
- If that fails, check Docker daemon DNS config on `fox`.

**A specific site always returns empty text**
- Some sites require JS to render content (Readability works on static HTML only). Check the raw response: `docker compose exec extractor python -c "import httpx; print(httpx.get('<URL>', follow_redirects=True, headers={'User-Agent':'Mozilla/5.0'}).text[:2000])"`
- If the HTML has no article body (just a Cloudflare challenge, JS loader, etc.), this service can't help — would need a headless browser.

**Port 8090 conflicts with something else**
- Pick a different host port in `docker-compose.yml` and update the n8n node URL accordingly.
