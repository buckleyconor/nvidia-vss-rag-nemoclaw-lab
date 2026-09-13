"""ADR-V09 / O24 — mapping raw OpenClaw hook events to the §6.3 vocabulary."""

from app.telemetry import TelemetryMapper, redact, skill_from_params


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def _read(skill, run="r"):
    return {"hook": "before_tool_call", "run_id": run, "tool_name": "read",
            "params": {"path": f"/home/sandbox/.openclaw/skills/{skill}/SKILL.md"}}


def test_skill_detected_from_any_nested_string():
    assert skill_from_params({"args": ["cat", "skills/vss-ask-video/SKILL.md"]}) == "vss-ask-video"
    assert skill_from_params({"path": "C:\\x\\skills\\vss-ask-video\\SKILL.md"}) == "vss-ask-video"
    assert skill_from_params({"path": "skills/other-tool/SKILL.md"}) is None
    assert skill_from_params({"path": "skills/vss-ask-video/README.md"}) is None
    assert skill_from_params(None) is None


def test_sequence_rationale_duration_and_completion():
    clock = Clock()
    mapper = TelemetryMapper(clock=clock)
    assert mapper.map({"hook": "llm_output", "run_id": "r", "text": "  "}) == []
    assert mapper.map({"hook": "llm_output", "run_id": "r",
                       "text": "Need the manual."}) == [("agent.token", {"text": "Need the manual."})]
    invoked = mapper.map(_read("vss-generate-video-report-rag"))
    assert invoked[0][0] == "skill.invoked"
    assert invoked[0][1]["rationale"] == "Need the manual."
    clock.now += 2.5
    switched = mapper.map(_read("vss-ask-video"))
    assert switched[0] == ("skill.completed", {"skill_name": "vss-generate-video-report-rag",
                                               "duration_ms": 2500, "outcome": "ok"})
    assert switched[1][0] == "skill.invoked"
    assert mapper.map({"hook": "after_tool_call", "run_id": "r", "tool_name": "exec",
                       "error": "curl: (7) connection refused"}) == []
    clock.now += 1
    ended = mapper.map({"hook": "agent_end", "run_id": "r"})
    assert ended[0][1]["outcome"] == "failed"
    assert "connection refused" in ended[0][1]["error"]
    assert mapper.map({"hook": "agent_end", "run_id": "r"}) == []


def test_recovery_after_error_completes_ok():
    mapper = TelemetryMapper(clock=Clock())
    mapper.map(_read("vss-ask-video"))
    mapper.map({"hook": "after_tool_call", "run_id": "r", "error": "timeout"})
    mapper.map({"hook": "after_tool_call", "run_id": "r"})
    assert mapper.map({"hook": "agent_end", "run_id": "r"})[0][1]["outcome"] == "ok"


def test_plain_tool_calls_emit_nothing_and_runs_are_independent():
    mapper = TelemetryMapper(clock=Clock())
    assert mapper.map({"hook": "before_tool_call", "run_id": "a", "tool_name": "exec",
                       "params": {"command": "curl vss:8000/health"}}) == []
    mapper.map(_read("vss-ask-video", run="a"))
    assert mapper.map({"hook": "agent_end", "run_id": "b"}) == []
    mapper.reset()
    assert mapper.map({"hook": "agent_end", "run_id": "a"}) == []


def test_no_rationale_is_never_synthesised():
    mapper = TelemetryMapper(clock=Clock())
    assert mapper.map(_read("vss-ask-video"))[0][1]["rationale"] is None


def test_rationale_is_consumed_not_inherited_by_the_next_skill():
    mapper = TelemetryMapper(clock=Clock())
    mapper.map({"hook": "llm_output", "run_id": "r", "text": "Report first."})
    assert mapper.map(_read("vss-generate-video-report-rag"))[0][1]["rationale"] == "Report first."
    invoked = mapper.map(_read("vss-ask-video"))[-1][1]
    assert invoked["rationale"] is None


def test_secrets_are_redacted_everywhere():
    text = ("curl -H 'Authorization: Bearer abc.def' -H 'x-api-key: s3cr3t' "
            "NGC=nvapi-ABCDEFGHIJKLMNOP token=hunter2 {\"api_key\": \"k1\"}")
    cleaned = redact(text)
    for secret in ("abc.def", "s3cr3t", "nvapi-ABCDEFGHIJKLMNOP", "hunter2", "k1"):
        assert secret not in cleaned
    mapper = TelemetryMapper(clock=Clock())
    out = mapper.map({"hook": "llm_output", "run_id": "r", "text": text})
    assert "s3cr3t" not in out[0][1]["text"]
    event = dict(_read("vss-ask-video"))
    event["params"] = dict(event["params"], headers={"x-api-key": "zzz-secret"})
    invoked = mapper.map(event)[-1][1]
    assert "zzz-secret" not in str(invoked["params"])


def test_oversized_params_are_truncated():
    mapper = TelemetryMapper(clock=Clock())
    event = _read("vss-ask-video")
    event["params"] = dict(event["params"], blob="x" * 5000)
    params = mapper.map(event)[0][1]["params"]
    assert set(params) == {"truncated"} and len(params["truncated"]) == 2000
