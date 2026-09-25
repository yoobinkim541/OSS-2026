"""
에이전트 도구 — OpenRouter(앱 안에서 직접)와 MCP(Claude Code / Codex)가 같은 정의를 씀
======================================================================================
도구는 SketchSession의 설정·획만 바꿉니다. 로봇을 움직이거나 파일을 쓰는 도구는
없습니다 (설계 문서: 모델은 관절각이나 G-code를 직접 실행하지 않음). 실제 드로잉은
사람이 실행기에서 확인(yes)해야만 시작됩니다.

도구 결과는 부분(part)의 목록입니다:
  {"type": "text", "text": ...}
  {"type": "image", "data": <base64 PNG>, "mime": "image/png"}
"""

import base64
import json

import cv2

from ..session import SessionError

SYSTEM_PROMPT = """당신은 사진을 로봇 팔(WLKATA Mirobot)이 펜으로 그릴 선 경로로 바꾸는 앱의 편집 도우미입니다.
사용자의 요청에 맞게 도구로 처리 설정을 바꾸고, 결과 그림을 직접 보고 확인한 뒤 필요한 획을 정리합니다.

작업 방식
- 먼저 get_state로 현재 상태를 보고, view로 원본과 결과를 눈으로 확인하세요.
- 설정을 바꾼 뒤에는 view로 결과를 다시 확인하고, 획 수·예상 시간의 변화를 사용자에게 알려 주세요.
- 잡음·배경·글씨처럼 필요 없는 획은 view(kind="strokes", numbered=true)로 번호를 확인한 뒤
  delete_strokes나 delete_region으로 지우세요. 좁은 영역은 region_mm로 확대해서 보세요.
- 설정을 다시 처리하면 이전 편집(획 삭제)은 사라집니다. 설정을 먼저 정하고 편집은 마지막에 하세요.
- 좌표는 종이 중심이 원점인 mm이며 x는 오른쪽, y는 위쪽이 +입니다.

주요 설정
- image_type: photo(실사, 배경 제거) / illustration(컬러 일러스트) / manga(흑백 만화, 망점 제거)
- detail: low / medium / high — 높을수록 선이 많고 오래 걸림
- median_ksize: 만화 망점 제거 (11 정도), dedupe_px: 이중선 제거 거리, merge_join_px: 획 이어붙이기 거리
- epsilon_px: 클수록 점·명령 수가 줄어 빨라지지만 곡선이 거칠어짐
- box_mm: 그림 긴 변 크기. 실행기 허용 범위를 넘으면 실제 드로잉 전 별도 확인이 필요함

로봇을 직접 움직이는 기능은 없습니다. 드로잉은 사용자가 내보내기 후 실행기에서 직접 시작합니다.
답변은 한국어로 짧고 분명하게 하세요."""

TOOLS = [
    {
        "name": "get_state",
        "description": "현재 이미지, 처리 설정, 결과(획 수, 예상 시간, 크기, 편집 기록), 시뮬레이션 결과를 JSON으로 돌려줍니다.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "view",
        "description": (
            "그림을 봅니다. kind: original(컬러 원본 — 처리 자체는 흑백으로 함), lines(선 후보), paper(A4 종이 미리보기, 펜 굵기 반영), "
            "strokes(획을 종이 mm 좌표로 확대, 10mm 격자). strokes에서 numbered=true면 획 번호가 붙고, "
            "region_mm=[x0,y0,x1,y1]로 일부만 확대할 수 있습니다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["original", "lines", "paper", "strokes"]},
                "numbered": {"type": "boolean"},
                "region_mm": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
            },
            "required": ["kind"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_params",
        "description": (
            "처리 설정을 바꾸고 다시 처리합니다(이전 획 편집은 사라짐). 넣은 항목만 바뀝니다. "
            "image_type/detail은 프리셋을 먼저 적용하고, 나머지 값은 그 위에 덮어씁니다. "
            "결과로 바뀐 설정과 획 수·예상 시간을 돌려줍니다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "image_type": {"type": "string", "enum": ["photo", "illustration", "manga"]},
                "detail": {"type": "string", "enum": ["low", "medium", "high"]},
                "canny_low": {"type": "number"}, "canny_high": {"type": "number"},
                "min_length_px": {"type": "number"}, "epsilon_px": {"type": "number"},
                "median_ksize": {"type": "integer"}, "dedupe_px": {"type": "integer"},
                "merge_join_px": {"type": "number"},
                "line_source": {"type": "string", "enum": ["canny", "dark"]},
                "rembg": {"type": "boolean"}, "box_mm": {"type": "number"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_strokes",
        "description": "번호로 획을 지웁니다(번호는 view kind=strokes numbered=true에서 확인). 지운 뒤 번호가 다시 매겨집니다.",
        "parameters": {
            "type": "object",
            "properties": {"ids": {"type": "array", "items": {"type": "integer"}, "minItems": 1}},
            "required": ["ids"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_region",
        "description": "종이 좌표(mm) 사각형 [x0,y0,x1,y1] 안(inside) 또는 밖(outside)에 있는 획을 지웁니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "region_mm": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                "mode": {"type": "string", "enum": ["inside", "outside"]},
            },
            "required": ["region_mm", "mode"],
            "additionalProperties": False,
        },
    },
    {
        "name": "undo",
        "description": "마지막 획 편집을 되돌립니다.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "simulate",
        "description": "로봇 기구학 시뮬레이션으로 관절 한계(Soft limit)를 검사합니다. 수십 초 걸릴 수 있습니다.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]
TOOL_NAMES = {t["name"] for t in TOOLS}


def image_part(img_bgr, max_side=1024):
    h, w = img_bgr.shape[:2]
    s = max_side / max(h, w)
    if s < 1:
        img_bgr = cv2.resize(img_bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img_bgr)
    return {"type": "image", "data": base64.b64encode(buf.tobytes()).decode("ascii"), "mime": "image/png"}


def text_part(obj):
    return {"type": "text", "text": obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)}


class AgentToolbox:
    """도구 실행기. on_change()는 세션이 바뀌었을 때 화면을 갱신하도록 GUI가 넘겨 줌."""

    def __init__(self, session, on_change=None):
        self.session = session
        self.on_change = on_change or (lambda what: None)

    def call(self, name, args):
        """(parts, is_error). 예외를 밖으로 던지지 않고 오류 문구로 돌려줌."""
        try:
            if name not in TOOL_NAMES:
                raise SessionError(f"알 수 없는 도구: {name}")
            return getattr(self, "_" + name)(**(args or {})), False
        except SessionError as e:
            return [text_part(f"오류: {e}")], True
        except TypeError as e:  # 잘못된 인자
            return [text_part(f"오류: 인자가 올바르지 않습니다 ({e})")], True
        except Exception as e:  # 예상 못 한 오류도 대화를 끊지 않게
            return [text_part(f"오류: {type(e).__name__}: {e}")], True

    # --- 도구 구현
    def _get_state(self):
        return [text_part(self.session.state())]

    def _view(self, kind, numbered=False, region_mm=None):
        img = self.session.render(kind, region_mm=region_mm, numbered=numbered)
        label = f"{kind}" + (" (번호)" if numbered else "") + (f" 영역 {region_mm}" if region_mm else "")
        return [text_part(f"그림: {label}"), image_part(img)]

    def _set_params(self, image_type=None, detail=None, **changes):
        s = self.session
        if image_type or detail:
            s.apply_preset(image_type, detail)
        applied = s.update_params(changes) if changes else {}
        s.run()
        self.on_change("result")
        st = s.state()
        return [text_part({"applied": applied, "image_type": st["image_type"], "detail": st["detail"],
                           "result": st.get("result")})]

    def _delete_strokes(self, ids):
        n = self.session.delete_strokes(ids)
        self.on_change("result")
        return [text_part({"deleted": n, "result": self.session.state().get("result")})]

    def _delete_region(self, region_mm, mode):
        n = self.session.delete_region(region_mm, mode)
        self.on_change("result")
        return [text_part({"deleted": n, "result": self.session.state().get("result")})]

    def _undo(self):
        desc = self.session.undo()
        self.on_change("result")
        return [text_part({"undone": desc, "result": self.session.state().get("result")})]

    def _simulate(self):
        summary = self.session.simulate()
        self.on_change("sim")
        return [text_part(summary)]
