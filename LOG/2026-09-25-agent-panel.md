# 2026-09-25 — LLM 에이전트 사이드 패널 (OpenRouter / Claude Code / Codex)

사용자 제안: 로컬에 설치된 Claude Code·Codex나 OpenRouter API 키를 연결하고, 오른쪽 사이드 패널에서 에이전트와 대화하며 세부 설정을 조작한다. LLM이 원본 이미지와 고전 CV 결과를 보고 리터치·편집하게 한다. UI는 사용자가 보여 준 ChatGPT 사이드 패널처럼, 앱의 라이트/다크 테마를 따른다.

로봇은 움직이지 않았습니다.

## 설계 결정

- **LLM이 선을 직접 그리지 않습니다.** 비전 LLM은 그림을 보고 판단하는 데는 강하지만, 픽셀 단위의 정확한 좌표를 내는 데는 약하고 결과가 매번 달라집니다. 그래서 LLM은 **도구(설정 변경, 획 삭제, 영역 삭제 등)를 고르는 역할만** 하고, 실제 편집은 결정적인 코드가 합니다. 편집 내용은 기록(`edit_log`)에 남고, 되돌릴 수 있습니다.
- **로봇 실행 도구는 두지 않습니다.** 설계 문서의 원칙("모델은 관절각이나 G-code를 직접 실행하지 않는다")을 따릅니다. 드로잉은 사용자가 내보낸 뒤 실행기에서 `yes`를 입력해야 시작됩니다.
- **연결 방식**
  - **OpenRouter:** 앱이 OpenAI 호환 API를 직접 호출하고 도구를 실행합니다(`requests`). 기본 모델은 `anthropic/claude-opus-5`입니다. 모델 목록은 OpenRouter의 공개 `/models`에서 "도구 호출 + 이미지 입력"을 둘 다 지원하는 모델만 골라 보여 줍니다. 2026-09-25 기준 460개 중 264개이고, `:batch` 전용 모델은 뺐습니다.
  - **Claude Code / Codex:** 사용자가 설치하고 로그인한 CLI를 앱이 실행합니다. 앱 도구는 **MCP 서버**로 공개하므로 도구 정의를 한 번만 쓰면 됩니다. 사용자 본인 PC에서 본인 계정으로 쓰는 용도입니다.

## 구조

```
[채팅 패널] ─┬─ OpenRouterBackend ─────────────── AgentToolbox ── SketchSession ── (GUI 갱신)
             ├─ ClaudeCodeBackend: claude -p ─┐
             └─ CodexBackend: codex exec ─────┴─ mcp_server.py (stdio) ─ bridge (127.0.0.1 + 토큰) ─ AgentToolbox
```

| 파일 | 역할 |
|---|---|
| `mirobot_sketch/session.py` | **SketchSession**: 이미지, 설정, 결과, 편집 기록(되돌리기), 시뮬레이션을 한곳에 둡니다. GUI 버튼과 에이전트 도구가 같은 상태를 바꿉니다. Tk에 의존하지 않아 단위 테스트가 가능합니다. |
| `agent/tools.py` | 도구 7개(get_state, view, set_params, delete_strokes, delete_region, undo, simulate)와 시스템 프롬프트. 도구가 실패해도 예외를 던지지 않고 "오류: …" 문구로 돌려줘서 LLM이 스스로 고칠 수 있습니다. |
| `agent/bridge.py` | CLI의 MCP 서버가 실행 중인 앱의 도구를 부르는 로컬 HTTP 통로입니다. 127.0.0.1에만 묶고, 매 요청마다 임의 토큰을 확인합니다. |
| `agent/mcp_server.py` | stdio MCP 서버(MCP SDK 2.2, 저수준 `Server`). 그림은 `ImageContent`로 넘깁니다. |
| `agent/backends.py` | 백엔드 3종과 공통 이벤트(text / tool / tool_done / error / done), OpenRouter 키 저장(Windows 자격 증명 관리자, keyring), 패널 설정 저장. |
| `agent/panel.py` | 오른쪽 채팅 패널(CustomTkinter). 테마 색은 (라이트, 다크) 쌍으로 지정합니다. |

**번호 붙은 획 그림:** 종이 mm 좌표로 확대하고, 10mm 격자를 긋고, 획마다 번호를 붙입니다. 에이전트가 "몇 번 획을 지울지"나 "어느 영역을 지울지"를 눈으로 고를 수 있습니다. 좁은 영역은 `region_mm`로 확대합니다.

## CLI 연동 세부

**Claude Code** (2.1.278)

```
claude -p --output-format stream-json --verbose --mcp-config <파일> --strict-mcp-config
       --tools "" --allowedTools mcp__mirobot --permission-mode dontAsk
       --append-system-prompt <지시> [--resume <세션>]
```

- `--tools ""`로 기본 도구(파일 수정·명령 실행 등)를 모두 끄고 앱 도구만 허용합니다.
- 요청문은 stdin으로 넘깁니다.
- 작업 폴더는 저장소 밖(`%APPDATA%\MirobotSketch\agent`)이라 프로젝트 설정을 읽지 않습니다.

**Codex** (0.155.1)

```
codex exec --json --skip-git-repo-check -c mcp_servers.mirobot.* -c sandbox_mode="read-only"
       -c approval_policy="never" -
```

- 이어서 대화할 때는 `codex exec resume <id>`를 씁니다.
- **문제:** `codex`가 npm이 만든 `.CMD` 파일이라, cmd.exe가 한글·따옴표 인자를 잘못 해석할 수 있습니다 → 뒤에 있는 실제 `codex.exe`를 찾아 직접 실행합니다.
- `resume`은 `-C`, `-s`를 받지 않아서, 작업 폴더는 프로세스 설정으로, 샌드박스는 `-c` 설정으로 지정합니다.
- Windows 경로는 TOML 리터럴 문자열(작은따옴표)로 넘깁니다.

**MCP 서버 실행 명령**
- 저장소나 pip 설치: `python -m mirobot_sketch.agent.mcp_server` (pythonw로 실행 중이면 python.exe로 바꿈. 표준 입출력 때문)
- .exe 배포판: `mirobot.exe mcp`

## 검증

**자동 테스트** `tests/test_agent.py` 19개 (전체 67개 통과, ResourceWarning을 오류로 취급해도 통과)
- 세션: 처리, 삭제와 되돌리기, 영역 밖 삭제, 잘못된 입력 → SessionError, 설정 범위 제한(`box_mm`는 실물 미확인 범위 120mm가 상한), 다시 처리하면 편집이 초기화됨
- 도구: 로봇 실행 도구 없음, view가 PNG를 돌려줌, 오류를 예외가 아닌 결과로 돌려줌, 화면 갱신 알림
- 브리지: 토큰이 틀리면 거부
- **MCP stdio 처음부터 끝까지:** 실제 서브프로세스로 initialize → tools/list → tools/call(이미지) → 잘못된 호출 시 isError
- **OpenRouter 도구 루프:** 로컬 가짜 서버로 도구 호출 → 결과 → 그림을 사용자 메시지로 붙이기 → 최종 답변, Bearer 키, 비용 합산. 키가 없을 때 안내
- **CLI 이벤트 해석:** Claude Code stream-json(세션 ID, 도구 이름, `--tools ""`, stdin) / 인증 오류를 한 번만 안내 / Codex JSONL(thread ID, mcp_tool_call, resume, 이어갈 때 시스템 지시를 반복하지 않음)

**실제 CLI**
- Claude Code: CLI 실행, 이벤트 수신, 세션 이어가기까지 동작했습니다. 그러나 **이 PC의 `claude` 로그인이 만료**돼("OAuth session expired") 모델 응답과 도구 호출은 확인하지 못했습니다. 이 오류를 발견하고, 같은 오류가 두 번 표시되던 문제를 고쳤습니다.
- Codex: 사용자의 **Codex 사용량이 소진**된 상태(2026-09-26 21:01 초기화)라 실행하지 않았습니다. 이벤트 형식은 문서화된 `codex exec --json` 스키마를 기준으로 구현했고 단위 테스트로만 확인했습니다. **실제 출력과 다를 수 있어** 사용량이 돌아오면 확인해야 합니다.
- OpenRouter: 키가 없어 실제 호출은 하지 않았습니다(공개 모델 목록 조회만).

**GUI**
- 가짜 백엔드가 실제 도구를 순서대로 호출하는 방식으로 화면 흐름을 확인했습니다.
  - 채팅 → set_params(detail=medium) → 왼쪽 상세도 버튼이 "보통"으로 자동으로 바뀜
  - delete_region → 상태 줄에 "획 편집 1건" 표시
- 라이트/다크 화면 캡처는 **PC가 잠겨(Windows 잠금 화면) 찍지 못했습니다.** 잠금이 풀린 뒤 다시 확인해야 합니다.

**코드 검사 중 고친 것**
- 치환 과정에서 문자열 안에 실제 줄바꿈이 들어가 문법 오류가 났습니다.
- 안내 문구를 붙인 뒤 비교해서 중복 방지 검사가 항상 실패했습니다.
- `except` 밖의 람다에서 `e`를 참조했습니다(실행 시 NameError).
- `pyproject.toml`이 `mirobot_sketch.agent` 하위 패키지를 빠뜨려, 설치본과 .exe에서 에이전트가 없어질 뻔했습니다.
- .exe 빌드에서 `collect_submodules("mcp")`가 `mcp.cli`(typer 필요)를 불러오며 종료해서 제외했습니다.

## 패키징

- `pyproject.toml`: 선택 설치 `[agent]` = mcp ≥ 2, keyring ≥ 25, requests ≥ 2.31. 하위 패키지 `mirobot_sketch.agent`를 포함했습니다.
- `.exe`: `mirobot.exe mcp` 하위 명령을 추가하고, MCP·keyring 백엔드를 숨은 import로 지정했습니다. Release 워크플로에서 `mirobot.exe mcp`가 종료 코드 2(안내 후 종료)인지 확인합니다. 모듈이 빠졌다면 1이 나옵니다.
- CI와 Release는 `[agent]`를 포함해 설치합니다.
- **로컬 .exe 재빌드 결과:** 10분 26초, 324MB (에이전트 추가로 28MB 증가)
  - `mirobot.exe mcp`를 브리지 없이 실행하면 종료 코드 2(정상 안내)입니다.
  - 브리지와 연결하면 initialize, 도구 7개, view 이미지 전달이 모두 파이썬 실행과 같습니다.
  - `MirobotSketch.exe`는 창이 떠서 유지됩니다(12.4초). 에이전트 패널을 띄우고 브리지를 시작하는 초기화 과정에서 오류가 없었습니다.
  - .exe 안에서 keyring(키 저장)이 동작하는지는 GUI 설정 창을 조작해야 확인할 수 있어서, 아직 확인하지 못했습니다.

## Claude Code 로그인 실패 원인 (사용자 질문: "로그인은 왜 안 되지?")

**확인한 사실**
- `claude` CLI가 쓰는 로그인 정보(`~/.claude/.credentials.json`)의 **갱신 토큰 만료 시각은 2026-09-23 17:52**이고, 접근 토큰도 유효하지 않았습니다. 갱신 토큰이 만료돼 자동 연장이 불가능합니다.
- `claude auth status` 결과는 `loggedIn: false`, `authMethod: none`이었습니다. 호스트 세션의 환경 변수를 걸러낸 뒤에도 같았습니다.
- 이 대화(Claude 데스크톱 앱)가 되는 것은, 데스크톱 앱이 CLI와 **별도로** 로그인을 관리하기 때문입니다.
- **결론:** 코드 문제가 아니라 CLI 로그인 만료입니다. 사용자가 `claude auth login`으로 다시 로그인해야 합니다. 로그인은 사용자가 직접 브라우저에서 해야 합니다.

**함께 발견해 고친 것**
1. **호스트 세션 환경 변수:** 앱이 Claude Code 세션 안에서 실행되면(개발 중 테스트 등), 그 세션 전용 환경 변수(`CLAUDECODE`, `CLAUDE_CODE_*`, `CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH`, 호스트가 주입한 `ANTHROPIC_BASE_URL` 등)가 자식 CLI로 넘어가 "로그인 갱신은 호스트가 한다"로 동작할 수 있었습니다. `clean_cli_env()`로 걸러냅니다. 사용자가 직접 정한 `ANTHROPIC_API_KEY`와, 중첩 실행이 아닐 때의 `ANTHROPIC_BASE_URL`은 유지합니다.
2. **로그인 사전 확인:** 요청을 보내고 약 15초 뒤 인증 오류가 뜨던 것을, 전송 전에 `claude auth status`(모델 호출 없음, 약 1.3초)로 확인하도록 바꿨습니다. 로그인이 안 돼 있으면 바로 `claude auth login` 안내를 보여 줍니다.
3. **안내 문구:** `/login` 대신 정확한 명령 `claude auth login`으로 고쳤습니다.
4. **테스트 2개 추가(전체 67개):** 로그인이 안 됐으면 CLI를 실행하지 않고 안내하는지, 호스트 세션 변수만 걸러내는지 확인합니다.

### 후속: 패널에서 바로 로그인
- **증상:** 사용자가 패널에 `/login`을 보냈더니 "/login isn't available in this environment"가 나왔습니다. 패널은 `claude -p`(비대화형)로 보내는데, 이 모드에는 `/login`이 없습니다. 또 이미 떠 있던 앱은 수정 전 코드라서 예전 안내(`/login`)가 그대로 보였습니다.
- **수정:**
  - 로그인 오류 카드에 **[로그인 창 열기]** 버튼을 추가했습니다. 누르면 `open_login_console()`이 **새 콘솔 창**에서 `claude auth login`(Codex는 `codex login`)을 실행하고, 브라우저 로그인은 사용자가 직접 합니다.
  - 패널 입력창에서 `/login`(또는 `/로그인`)을 입력하면 모델로 보내지 않고 같은 창을 엽니다.
- **테스트:** 로그인 명령 구성, 새 창 실행, 실패 처리를 확인하는 테스트를 추가했습니다(전체 68개 통과).

## 남은 일

1. PC 잠금이 풀리면 패널 화면(라이트/다크)을 캡처해 확인합니다.
2. 사용자가 `claude auth login`으로 다시 로그인한 뒤, 실제 대화로 도구 호출을 확인합니다(설정 변경 → 그림 보기 → 획 삭제).
3. Codex 사용량이 초기화되면(9/26 21:01) 실제 `--json` 출력 형식이 파서와 맞는지 확인합니다.
4. OpenRouter 키를 받으면 실제 모델로 확인합니다.
