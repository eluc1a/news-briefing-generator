import subprocess
from pathlib import Path


class PrintError(RuntimeError):
    pass


def print_pdf(pdf_path: Path, *, queue: str = "brother") -> str:
    try:
        result = subprocess.run(
            ["lp", "-d", queue, "-o", "sides=two-sided-long-edge", str(pdf_path)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise PrintError(f"lp failed (exit {e.returncode}): {e.stderr.strip()}") from e
    return result.stdout.strip()
