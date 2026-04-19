import httpx


def notify_printed(*, topic: str | None, pages: int = 2) -> None:
    if not topic:
        return
    httpx.post(
        f"https://ntfy.sh/{topic}",
        data=f"Morning Fox briefing printed ({pages} pages).".encode(),
        headers={
            "Title": "The Morning Fox",
            "Tags": "newspaper",
        },
        timeout=10,
    )


def notify_failure(*, topic: str | None, reason: str) -> None:
    if not topic:
        return
    httpx.post(
        f"https://ntfy.sh/{topic}",
        data=f"Briefing failed: {reason}".encode(),
        headers={
            "Title": "The Morning Fox — failure",
            "Priority": "high",
            "Tags": "warning,newspaper",
        },
        timeout=10,
    )
