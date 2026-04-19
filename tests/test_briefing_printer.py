import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jina_clone.briefing.printer import PrintError, print_pdf


def test_print_pdf_invokes_lp():
    with patch("jina_clone.briefing.printer.subprocess.run") as run:
        run.return_value = MagicMock(stdout="request id is brother-42 (1 file(s))\n", returncode=0)
        result = print_pdf(Path("/tmp/x.pdf"), queue="brother")
        run.assert_called_once_with(
            ["lp", "-d", "brother", "/tmp/x.pdf"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "brother-42" in result


def test_print_pdf_raises_print_error_on_failure():
    with patch("jina_clone.briefing.printer.subprocess.run") as run:
        run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=["lp"], stderr="lp: queue not found"
        )
        with pytest.raises(PrintError) as exc:
            print_pdf(Path("/tmp/x.pdf"), queue="nope")
        assert "queue not found" in str(exc.value)
