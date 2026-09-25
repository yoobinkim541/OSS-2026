"""LLM 에이전트: 오른쪽 채팅 패널에서 대화로 처리 설정과 획을 조작.

연결 방식
  - OpenRouter API 키: 앱이 직접 API를 호출하고 도구를 실행 (backends.OpenRouterBackend)
  - 로컬 Claude Code / Codex: CLI를 실행하고, 앱 도구는 MCP 서버로 공개
    (backends.ClaudeCodeBackend / CodexBackend -> mcp_server.py -> bridge.py -> 앱)
"""
