import httpx


def notify_printed(*, topic: str | None, title: str, pages: int = 2) -> None:
    if not topic:
        return
    httpx.post(
        f"https://ntfy.sh/{topic}",
        data=f"{title} briefing printed ({pages} pages).".encode(),
        headers={
            "Title": title,
            "Tags": "newspaper",
        },
        timeout=10,
    )


def notify_failure(*, topic: str | None, title: str, reason: str) -> None:
    if not topic:
        return
    httpx.post(
        f"https://ntfy.sh/{topic}",
        data=f"Briefing failed: {reason}".encode(),
        headers={
            "Title": f"{title} — failure",
            "Priority": "high",
            "Tags": "warning,newspaper",
        },
        timeout=10,
    )
