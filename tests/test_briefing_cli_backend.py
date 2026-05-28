import asyncio
import json

import pytest

from jina_clone.briefing import generator


class _FakeProc:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self.killed = False
        self.sent_stdin = None

    async def communicate(self, input=None):
        self.sent_stdin = input
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True


def _envelope(**over):
    base = {
        "is_error": False,
        "result": "```json\n{\"x\": 1}\n```",
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 2,
            "cache_creation_input_tokens": 3,
        },
        "total_cost_usd": 0.001,
    }
    base.update(over)
    return json.dumps(base).encode()


async def test_cli_call_llm_strips_api_key_and_parses(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-removed")
    captured = {}

    async def fake_exec(*argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs.get("env")
        return _FakeProc(_envelope())

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    generator.reset_usage()

    out = await generator._cli_call_llm("PROMPT", system="SYS", model="sonnet")

    assert out == '{"x": 1}'  # fences stripped
    assert "ANTHROPIC_API_KEY" not in captured["env"]
    assert captured["env"]["MAX_THINKING_TOKENS"] == "0"  # thinking disabled
    assert "--system-prompt" in captured["argv"]
    assert "SYS" in captured["argv"]
    assert "--setting-sources" in captured["argv"]  # isolated from project context
    totals = generator.pop_usage_totals()
    assert totals["calls"] == 1
    assert totals["input"] == 10
    assert totals["output"] == 5
    assert totals["cost"] == pytest.approx(0.001)


async def test_cli_call_llm_raises_on_is_error(monkeypatch):
    async def fake_exec(*argv, **kwargs):
        return _FakeProc(_envelope(is_error=True, result="rate limited"), returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(generator.GeneratorFailure):
        await generator._cli_call_llm("P", system="S", model="m")


async def test_cli_call_llm_raises_on_nonzero_exit(monkeypatch):
    async def fake_exec(*argv, **kwargs):
        return _FakeProc(b"", stderr=b"boom", returncode=2)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(generator.GeneratorFailure):
        await generator._cli_call_llm("P", system="S", model="m")


async def test_cli_call_llm_kills_and_raises_on_timeout(monkeypatch):
    class _HangProc:
        returncode = None

        def __init__(self):
            self.killed = False

        async def communicate(self, input=None):
            await asyncio.sleep(10)

        def kill(self):
            self.killed = True

        async def wait(self):
            return self.returncode

    proc = _HangProc()

    async def fake_exec(*argv, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(generator, "CLI_TIMEOUT", 0.05)
    with pytest.raises(generator.GeneratorFailure):
        await generator._cli_call_llm("P", system="S", model="m")
    assert proc.killed


async def test_default_backend_cli_routes_to_cli(monkeypatch):
    monkeypatch.setattr(generator, "BRIEFING_LLM_BACKEND", "cli")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # cli must not need it
    called = {}

    async def fake_cli(prompt, *, system, model):
        called["args"] = (prompt, system, model)
        return "OK"

    monkeypatch.setattr(generator, "_cli_call_llm", fake_cli)
    wrapper = generator._build_default_call_llm("SYSPROMPT", None)
    out = await wrapper(None, "USERMSG")

    assert out == "OK"
    assert called["args"] == ("USERMSG", "SYSPROMPT", generator.MODEL)


async def test_backend_api_uses_real_call(monkeypatch):
    monkeypatch.setattr(generator, "BRIEFING_LLM_BACKEND", "api")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    called = {}

    async def fake_real(cl, prompt, *, system):
        called["system"] = system
        return "R"

    monkeypatch.setattr(generator, "_real_call_llm", fake_real)
    wrapper = generator._build_default_call_llm("SYS", None)
    out = await wrapper(object(), "MSG")

    assert out == "R"
    assert called["system"] == "SYS"
