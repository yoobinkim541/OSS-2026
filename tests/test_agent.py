"""에이전트 기능 테스트: 세션 편집, 도구, 로컬 브리지+MCP, OpenRouter 도구 루프, CLI 이벤트 해석.

LLM이나 네트워크 없이 돌아갑니다 (OpenRouter는 로컬 가짜 서버, CLI는 미리 준비한 이벤트).

    python -m unittest discover -s tests -v
"""

import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mirobot_sketch import sketch_pipeline as sp  # noqa: E402
from mirobot_sketch import stages  # noqa: E402
from mirobot_sketch.agent import backends as bk  # noqa: E402
from mirobot_sketch.agent.bridge import BridgeClient, BridgeServer  # noqa: E402
from mirobot_sketch.agent.tools import TOOLS, AgentToolbox  # noqa: E402
from mirobot_sketch.session import SessionError, SketchSession  # noqa: E402


def make_image(path):
    """테스트용 선화: 큰 사각형 + 원 + 왼쪽 위 작은 잡음 점들."""
    img = np.full((400, 400), 255, np.uint8)
    cv2.rectangle(img, (80, 80), (320, 320), 0, 3)
    cv2.circle(img, (200, 200), 60, 0, 3)
    for x in range(20, 60, 12):
        cv2.line(img, (x, 20), (x + 6, 30), 0, 2)
    cv2.imwrite(str(path), img)


class SessionTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile

        cls.tmp = tempfile.TemporaryDirectory()
        cls.img = Path(cls.tmp.name) / "t.png"
        make_image(cls.img)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def new_session(self):
        s = SketchSession()
        s.set_image(self.img)
        s.apply_preset("illustration", "medium")
        s.run()
        return s


class SessionTest(SessionTestBase):
    def test_run_and_state(self):
        s = self.new_session()
        st = s.state()["result"]
        self.assertGreater(st["strokes"], 1)
        self.assertEqual(st["edits"], [])

    def test_original_is_color_and_aligned_with_gray(self):
        import tempfile
        s = self.new_session()
        orig = s.render("original")
        self.assertEqual(orig.ndim, 3)
        self.assertEqual(orig.shape[:2], s.result["base"].shape)   # 획 좌표를 겹쳐 그릴 수 있게 같은 크기
        # 컬러가 남아 있고(흑백 변환 안 함), 투명 PNG는 흰 배경으로 합성
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "rgba.png"
            img = np.zeros((40, 60, 4), np.uint8)
            img[:, :30] = (0, 0, 255, 255)          # 왼쪽: 불투명 빨강
            cv2.imwrite(str(p), img)                # 오른쪽: 완전 투명
            c = sp.load_color(p, max_side=60)
        self.assertEqual(c.shape, (40, 60, 3))
        self.assertEqual(tuple(int(v) for v in c[20, 5]), (0, 0, 255))
        self.assertEqual(tuple(int(v) for v in c[20, 55]), (255, 255, 255))

    def test_delete_and_undo(self):
        s = self.new_session()
        n = s.state()["result"]["strokes"]
        self.assertEqual(s.delete_strokes([0]), 1)
        self.assertEqual(s.state()["result"]["strokes"], n - 1)
        self.assertIsNotNone(s.undo())
        self.assertEqual(s.state()["result"]["strokes"], n)
        self.assertIsNone(s.undo())   # 더 되돌릴 것이 없음

    def test_delete_region_outside_keeps_only_region(self):
        s = self.new_session()
        s.delete_region([-20, -20, 20, 20], "outside")
        for stroke in s.result["strokes_mm"]:
            inside = (np.abs(np.asarray(stroke)) <= 20).all(axis=1).mean()
            self.assertGreaterEqual(inside, 0.5)

    def test_invalid_inputs_raise_session_error(self):
        s = self.new_session()
        with self.assertRaises(SessionError):
            s.delete_strokes([10 ** 6])
        with self.assertRaises(SessionError):
            s.update_params({"nope": 1})
        with self.assertRaises(SessionError):
            s.apply_preset("watercolor")

    def test_only_changed_stages_recompute(self):
        s = self.new_session()
        before = dict(s.pipeline.run_counts)
        s.update_params({"epsilon_px": 2.5})
        s.run()
        changed = {k for k in before if s.pipeline.run_counts[k] != before[k]}
        self.assertEqual(changed, {"simplify"})

    def test_line_source_is_mapped_to_edge_mode(self):
        s = self.new_session()
        self.assertEqual(s.update_params({"line_source": "dark"}), {"edge_mode": "dark"})
        self.assertEqual(s.update_params({"line_source": "canny"}), {"edge_mode": "luma"})
        with self.assertRaises(SessionError):
            s.update_params({"edge_mode": "rainbow"})

    def test_stale_run_returns_none(self):
        s = self.new_session()
        s.update_params({"canny_low": 70})
        real = s.pipeline.run

        def bump_then_run(*a, **k):
            s.generation += 1        # 계산 시작 직후 사용자가 값을 또 바꾼 상황
            return real(*a, **k)

        s.pipeline.run = bump_then_run
        self.assertIsNone(s.run())
        s.pipeline.run = real
        self.assertIsNotNone(s.run_current())

    def test_every_stage_renders_same_size_even_for_tiny_transparent_png(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "tiny.png"
            img = np.zeros((60, 90, 4), np.uint8)
            cv2.circle(img, (45, 30), 20, (0, 0, 0, 255), 2)   # 투명 바탕 위 검은 원
            cv2.imwrite(str(p), img)
            s = SketchSession()
            s.set_image(p)
            s.run_current()
            h, w = s.result["base"].shape
            for kind in ("original", *stages.PIPELINE_IDS, "edit", "lines"):
                self.assertEqual(s.render(kind).shape[:2], (h, w), kind)

    def test_state_lists_stages_with_values(self):
        st = self.new_session().state()
        ids = [x["id"] for x in st["stages"]]
        self.assertEqual(ids, [x.id for x in stages.ALL_STAGES])
        self.assertIn("edge_mode", st["stages"][2]["params"])

    def test_update_params_clamps_to_safe_range(self):
        s = self.new_session()
        applied = s.update_params({"box_mm": 500, "median_ksize": -3})
        self.assertEqual(applied["box_mm"], 120)       # 실물 미확인 범위(±60mm)가 상한
        self.assertEqual(applied["median_ksize"], 0)

    def test_rerun_clears_edits(self):
        s = self.new_session()
        s.delete_strokes([0])
        s.run()
        self.assertEqual(s.edit_log, [])
        self.assertEqual(s.history, [])


class ToolboxTest(SessionTestBase):
    def test_tools_do_not_include_robot_execution(self):
        names = {t["name"] for t in TOOLS}
        self.assertFalse(names & {"execute", "draw", "run_robot", "send_gcode"})

    def test_view_returns_png_image(self):
        tb = AgentToolbox(self.new_session())
        parts, err = tb.call("view", {"kind": "strokes", "numbered": True})
        self.assertFalse(err)
        img = parts[1]
        self.assertEqual(img["mime"], "image/png")
        import base64
        self.assertTrue(base64.b64decode(img["data"]).startswith(b"\x89PNG"))

    def test_errors_are_returned_not_raised(self):
        tb = AgentToolbox(SketchSession())
        for name, args in (("view", {"kind": "paper"}), ("unknown", {}), ("delete_strokes", {"wrong": 1})):
            parts, err = tb.call(name, args)
            self.assertTrue(err)
            self.assertTrue(parts[0]["text"].startswith("오류"))

    def test_set_params_notifies_screen(self):
        changes = []
        tb = AgentToolbox(self.new_session(), on_change=changes.append)
        tb.call("set_params", {"detail": "low"})
        self.assertEqual(changes, ["result"])


class BridgeAndMcpTest(SessionTestBase):
    def test_bridge_requires_token(self):
        br = BridgeServer(AgentToolbox(self.new_session())).start()
        try:
            self.assertEqual(len(BridgeClient(br.url, br.token).tools()), len(TOOLS))
            with self.assertRaises(Exception):
                BridgeClient(br.url, "wrong-token").tools()
        finally:
            br.stop()

    def test_mcp_stdio_server_end_to_end(self):
        import importlib.util
        if importlib.util.find_spec("mcp") is None:
            self.skipTest("mcp 패키지 없음 (pip install -e \".[agent]\")")
        br = BridgeServer(AgentToolbox(self.new_session())).start()
        env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8", **br.env())
        p = subprocess.Popen([sys.executable, "-m", "mirobot_sketch.agent.mcp_server"], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True, encoding="utf-8")

        def rpc(i, method, params):
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params}) + "\n")
            p.stdin.flush()
            return json.loads(p.stdout.readline())

        try:
            r = rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "t", "version": "0"}})
            self.assertEqual(r["result"]["serverInfo"]["name"], "mirobot")
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            p.stdin.flush()
            r = rpc(2, "tools/list", {})
            self.assertEqual({t["name"] for t in r["result"]["tools"]}, {t["name"] for t in TOOLS})
            r = rpc(3, "tools/call", {"name": "view", "arguments": {"kind": "paper"}})
            self.assertEqual([c["type"] for c in r["result"]["content"]], ["text", "image"])
            r = rpc(4, "tools/call", {"name": "delete_strokes", "arguments": {"ids": [10 ** 6]}})
            self.assertTrue(r["result"]["isError"])
        finally:
            p.stdin.close()
            p.wait(timeout=10)
            p.stdout.close()
            p.stderr.close()
            br.stop()


class FakeOpenRouter:
    """chat/completions 흉내: 첫 요청엔 도구 호출(view), 다음 요청엔 최종 답변."""

    def __init__(self):
        self.requests = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append({"auth": self.headers.get("Authorization"), "body": body})
                if len(fake.requests) == 1:
                    msg = {"role": "assistant", "content": "그림을 볼게요.", "tool_calls": [
                        {"id": "c1", "type": "function", "function": {"name": "view", "arguments": '{"kind":"paper"}'}}]}
                else:
                    msg = {"role": "assistant", "content": "확인했습니다."}
                data = json.dumps({"choices": [{"message": msg}], "usage": {"cost": 0.001}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


class OpenRouterBackendTest(SessionTestBase):
    def test_tool_loop_with_image_injection(self):
        fake = FakeOpenRouter()
        try:
            with mock.patch.object(bk, "OPENROUTER_URL", fake.url):
                b = bk.OpenRouterBackend(AgentToolbox(self.new_session()), lambda: "sk-test", "test/model")
                events = []
                b.send("결과를 봐줘", events.append)
        finally:
            fake.httpd.shutdown()
            fake.httpd.server_close()
        types_ = [e["type"] for e in events]
        self.assertEqual(types_, ["text", "tool", "tool_done", "text", "done"])
        self.assertEqual(fake.requests[0]["auth"], "Bearer sk-test")
        second = fake.requests[1]["body"]["messages"]
        self.assertEqual(second[-2]["role"], "tool")                    # 도구 결과(글자)
        self.assertEqual(second[-1]["content"][1]["type"], "image_url")  # 그림은 사용자 메시지로
        self.assertIn("$0.0020", events[-1]["info"])

    def test_missing_key_reports_error(self):
        b = bk.OpenRouterBackend(AgentToolbox(SketchSession()), lambda: None)
        events = []
        b.send("안녕", events.append)
        self.assertEqual(events[0]["type"], "error")
        self.assertIn("API 키", events[0]["text"])


class CliEventParsingTest(unittest.TestCase):
    def run_backend(self, backend_cls, lines, exit_code=0):
        br = mock.Mock()
        br.env.return_value = {"MIROBOT_BRIDGE_URL": "http://x", "MIROBOT_BRIDGE_TOKEN": "t"}
        b = backend_cls(br)

        def fake_run(cmd, stdin_text, on_line):
            fake_run.cmd, fake_run.stdin = cmd, stdin_text
            for ev in lines:
                on_line(ev)
            return exit_code, ""

        events = []
        with mock.patch.object(backend_cls, "available", staticmethod(lambda: "cli.exe")), \
                mock.patch.object(bk.ClaudeCodeBackend, "logged_in", staticmethod(lambda exe: True)), \
                mock.patch.object(b, "_run", fake_run):
            b.send("획 줄여줘", events.append)
        return b, events, fake_run

    def test_claude_code_stream_json(self):
        lines = [
            {"type": "system", "subtype": "init", "session_id": "s-1",
             "mcp_servers": [{"name": "mirobot", "status": "connected"}]},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "설정을 바꿀게요."},
                {"type": "tool_use", "name": "mcp__mirobot__set_params", "input": {"detail": "low"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": False}]}},
            {"type": "result", "subtype": "success", "is_error": False, "session_id": "s-1", "total_cost_usd": 0.01},
        ]
        b, events, run = self.run_backend(bk.ClaudeCodeBackend, lines)
        self.assertEqual([e["type"] for e in events], ["text", "tool", "tool_done", "done"])
        self.assertEqual(events[1]["name"], "set_params")
        self.assertEqual(b.session_id, "s-1")
        self.assertIn("--strict-mcp-config", run.cmd)
        self.assertEqual(run.cmd[run.cmd.index("--tools") + 1], "")      # 기본 도구 모두 끔
        self.assertEqual(run.stdin, "획 줄여줘")                          # 요청은 stdin으로

    def test_claude_code_auth_error_is_explained_once(self):
        msg = "Failed to authenticate: OAuth session expired"
        lines = [{"type": "assistant", "message": {"content": [{"type": "text", "text": msg}]}},
                 {"type": "result", "is_error": True, "result": msg}]
        _, events, _ = self.run_backend(bk.ClaudeCodeBackend, lines, exit_code=1)
        errors = [e["text"] for e in events if e["type"] == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("claude auth login", errors[0])
        self.assertNotIn(msg, errors[0])   # 같은 문구를 두 번 보여주지 않음

    def test_not_logged_in_is_reported_before_running(self):
        b = bk.ClaudeCodeBackend(mock.Mock())
        events = []
        with mock.patch.object(bk.ClaudeCodeBackend, "available", staticmethod(lambda: "claude.exe")), \
                mock.patch.object(bk.ClaudeCodeBackend, "logged_in", staticmethod(lambda exe: False)), \
                mock.patch.object(b, "_run") as run:
            b.send("안녕", events.append)
        run.assert_not_called()   # 모델 호출(사용량) 없이 바로 안내
        self.assertEqual(events[0]["action"], "login")   # 패널이 [로그인 창 열기] 버튼을 붙임

    def test_login_console_runs_login_command_in_new_window(self):
        with mock.patch.object(bk.ClaudeCodeBackend, "available", staticmethod(lambda: "C:/x/claude.exe")):
            argv = bk.ClaudeCodeBackend(mock.Mock()).login_argv()
        self.assertEqual(argv, ["C:/x/claude.exe", "auth", "login"])
        with mock.patch.object(bk.subprocess, "Popen") as popen:
            self.assertTrue(bk.open_login_console(argv))
        cmd = popen.call_args.args[0]
        self.assertIn("auth login", " ".join(cmd))
        self.assertNotIn("CLAUDECODE", popen.call_args.kwargs["env"])
        with mock.patch.object(bk.subprocess, "Popen", side_effect=OSError):
            self.assertFalse(bk.open_login_console(argv))

    def test_host_session_env_is_removed_for_child_cli(self):
        host = {"PATH": "x", "CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "desktop",
                "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH": "1", "ANTHROPIC_BASE_URL": "http://127.0.0.1:1",
                "ANTHROPIC_API_KEY": "user-key", "OPENROUTER_API_KEY": "k"}
        self.assertEqual(set(bk.clean_cli_env(host)), {"PATH", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"})
        # 다른 Claude Code 세션 안이 아니면 사용자가 직접 정한 ANTHROPIC_BASE_URL은 유지
        self.assertIn("ANTHROPIC_BASE_URL", bk.clean_cli_env({"ANTHROPIC_BASE_URL": "https://proxy"}))

    def test_codex_json_events_and_resume(self):
        lines = [
            {"type": "thread.started", "thread_id": "th-9"},
            {"type": "item.started", "item": {"type": "mcp_tool_call", "tool": "view", "arguments": {"kind": "paper"}}},
            {"type": "item.completed", "item": {"type": "mcp_tool_call", "tool": "view", "status": "completed"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "확인했어요."}},
            {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}},
        ]
        b, events, run = self.run_backend(bk.CodexBackend, lines)
        self.assertEqual([e["type"] for e in events], ["tool", "tool_done", "text", "done"])
        self.assertEqual(b.session_id, "th-9")
        self.assertIn("mcp_servers.mirobot.command=", " ".join(run.cmd))
        self.assertTrue(run.stdin.startswith("당신은"))   # 첫 요청에 시스템 지시 포함
        # 같은 백엔드로 다음 요청을 보내면 저장한 세션으로 이어감
        seen = {}
        with mock.patch.object(bk.CodexBackend, "available", staticmethod(lambda: "cli.exe")), \
                mock.patch.object(b, "_run", lambda cmd, s, f: (seen.update(cmd=cmd, stdin=s), (0, ""))[1]):
            b.send("다음", lambda e: None)
        self.assertEqual(seen["cmd"][1:4], ["exec", "resume", "th-9"])
        self.assertEqual(seen["stdin"], "다음")   # 이어갈 때는 시스템 지시를 다시 붙이지 않음


if __name__ == "__main__":
    unittest.main()
