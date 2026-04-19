Article Extractor Service — Implementation Plan
Overview
A self-hosted HTTP microservice that accepts a URL, fetches its HTML, extracts the main article content using Readability, and returns clean text. Designed to run on the fox homelab server as a Docker container and be called from n8n.

Project Structure
A single Python project directory containing:

FastAPI application entry point
Requirements file
Dockerfile
docker-compose.yml — a standalone file defining the extractor service, intended to be copy-pasted/merged into the existing homelab compose rather than run independently
A .env file for configuration


Dependencies

fastapi — HTTP framework
uvicorn — ASGI server
httpx — async HTTP client for fetching pages
readability-lxml — article content extraction
beautifulsoup4 — strip HTML tags from Readability output to return plain text
python-dotenv — environment variable loading


API Design
Single endpoint: GET /extract
Query params:

url (required) — the article URL to fetch and extract

Response JSON:

url — echo of the input URL
title — extracted article title
text — plain text of the article body (HTML stripped)
error — null on success, string message on failure

Behavior:

If the URL is unreachable or times out, return a 200 with error populated rather than raising an HTTP exception — this prevents n8n from treating it as a workflow failure
Truncate text to 4000 characters max to keep Claude API token usage reasonable. Make this limit configurable via env var.


Fetch Behavior

Use a realistic browser User-Agent string to avoid basic bot blocking
Follow redirects automatically
Set a request timeout of 15 seconds
If the response is not text/html content type (e.g. a PDF), return an error message explaining the content type is unsupported rather than attempting to parse it


Content Extraction Behavior

Pass raw HTML to Readability to get the article content as HTML
Strip all HTML tags from that output to produce plain text
Collapse multiple whitespace/newlines into single spaces
Return the title and plain text body


Configuration via .env

PORT — port to run the service on (default 8080)
MAX_TEXT_LENGTH — max characters to return (default 4000)
REQUEST_TIMEOUT — seconds before giving up on a fetch (default 15)


Docker

Base image: python:3.12-slim
Install dependencies from requirements file
Run with uvicorn on 0.0.0.0 at the configured port
docker-compose service named extractor, port mapped to 8080:8080, with restart: always


Health Check
A GET /health endpoint that returns {"status": "ok"} — useful for Docker health checks and verifying the service is up from n8n before the workflow runs.

n8n Integration Notes (include as a comment or README)

Call the service via http://HOST_LAN_IP:8080/extract?url={{$json.link}}
Use LAN IP rather than hostname since n8n runs inside Docker and may not resolve hostnames
The text field from the response is what gets passed into the Claude API prompt
Pair with a Wait node (2-3 seconds) between items to avoid hammering target sites


README
Include a short README covering:

What the service does
How to run it locally with docker-compose
The API endpoint and example curl call
How to wire it into n8n
