"""
Mirobot Sketch — 사진 -> 스케치 -> 로봇용 획(stroke) 데이터 GUI
===============================================================
사진을 열고 이미지 종류를 고르면 추천 설정이 들어갑니다. 결과는 A4 종이 위에
실제 크기와 펜 굵기로 미리 보여 주고, 예상 시간과 로봇 시뮬레이션(관절 한계)
결과를 함께 표시합니다. 내보낸 JSON은 그대로 robot/draw_executor.py에 넣습니다.

    mirobot-sketch                         (저장소에서는 python CV/gui_sketch.py)
    mirobot-draw <저장한.json>             (dry-run)
    mirobot-draw <저장한.json> --execute   (실제 드로잉)

화면: CustomTkinter (pip install customtkinter)
처리 로직: sketch_pipeline.py / paper_mapping.py / presets.py
명령줄 버전: make_strokes.py
"""

import json
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import cv2
import matplotlib
from matplotlib import font_manager
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

try:
    import customtkinter as ctk
except ImportError:  # 설치 안내 후 종료
    print("CustomTkinter가 필요합니다:  pip install customtkinter")
    raise

from . import draw_executor as de
from . import paper_mapping as pm
from . import paths, presets
from . import sketch_pipeline as sp
from .session import SketchSession

# 한글이 네모로 깨지지 않도록 설치된 한글 글꼴 사용 (Windows: 맑은 고딕)
FONT = "Malgun Gothic"
for _font in ("Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR"):
    if any(f.name == _font for f in font_manager.fontManager.ttflist):
        FONT = _font
        matplotlib.rcParams["font.family"] = _font
        break
matplotlib.rcParams["axes.unicode_minus"] = False

ACCENT = ("#2563eb", "#3b82f6")          # (라이트, 다크)
CARD = ("#ffffff", "#1f2430")
BG = ("#eef1f6", "#141821")
MUTED = ("#6b7280", "#9aa3b2")
TEXT = ("#1f2937", "#e5e7eb")
OK, WARN, BAD = "#16a34a", "#d97706", "#dc2626"

TYPE_KEYS = list(presets.IMAGE_TYPES)                          # photo / illustration / manga
TYPE_LABELS = [presets.IMAGE_TYPES[k]["label"] for k in TYPE_KEYS]
DETAIL_KEYS = ["low", "medium", "high"]
DETAIL_LABELS = ["낮음", "보통", "높음"]


def font(size=13, weight="normal"):
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


class Card(ctk.CTkFrame):
    """제목이 있는 둥근 카드."""

    def __init__(self, master, title=None, **kw):
        super().__init__(master, fg_color=CARD, corner_radius=14, **kw)
        if title:
            ctk.CTkLabel(self, text=title, font=font(14, "bold"), anchor="w").pack(fill="x", padx=14, pady=(12, 4))


class StatCard(ctk.CTkFrame):
    """아래쪽 요약 카드: 제목 / 큰 값 / 설명."""

    def __init__(self, master, title):
        super().__init__(master, fg_color=CARD, corner_radius=14)
        ctk.CTkLabel(self, text=title, font=font(12), text_color=MUTED, anchor="w").pack(fill="x", padx=14, pady=(10, 0))
        self.value = ctk.CTkLabel(self, text="—", font=font(24, "bold"), anchor="w")
        self.value.pack(fill="x", padx=14)
        self.sub = ctk.CTkLabel(self, text="", font=font(11), text_color=MUTED, anchor="w", justify="left",
                                wraplength=260)
        self.sub.pack(fill="x", padx=14, pady=(0, 10))

    def set(self, value, sub="", color=None):
        self.value.configure(text=value, text_color=color or ("#111827", "#f3f4f6"))
        self.sub.configure(text=sub)


class SketchApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Mirobot Sketch")
        self.root.geometry("1560x940")
        self.root.minsize(1200, 760)
        self.root.configure(fg_color=BG)
        self._set_icon()

        self.cfg = de.load_config()
        # 이미지·설정·결과·편집 기록은 세션 하나에 둠 (화면 버튼과 에이전트 도구가 함께 사용)
        self.session = SketchSession(self.cfg)
        self.busy = False
        self._agent_busy = False
        # 작업 스레드 -> 화면: Tkinter는 스레드에 안전하지 않으므로 작업 스레드는 큐에
        # 할 일만 넣고, 메인 스레드가 주기적으로 꺼내 실행한다.
        self._ui_queue = queue.Queue()

        self._build_ui()
        self.apply_type_preset()
        self._init_agent()
        self._poll_ui_queue()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # 세션에서 읽는 값
    @property
    def result(self):
        return self.session.result

    @property
    def sim_result(self):
        return self.session.sim["raw"] if self.session.sim else None

    @property
    def img_path(self):
        return self.session.image_path

    def ui(self, fn, *args):
        """에이전트 패널 등 다른 모듈이 화면 갱신을 요청할 때 사용 (스레드 안전)."""
        self._ui(fn, *args)

    def _ui(self, fn, *args):
        """작업 스레드에서 화면 갱신을 요청할 때 사용."""
        self._ui_queue.put((fn, args))

    def _poll_ui_queue(self):
        try:
            while True:
                fn, args = self._ui_queue.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.root.after(50, self._poll_ui_queue)

    # ------------------------------------------------------------------ 창
    def _set_icon(self):
        """창·작업표시줄 아이콘 (assets/make_icon.py로 생성). 없으면 기본 아이콘."""
        try:
            if sys.platform.startswith("win") and paths.asset("app_icon.ico").exists():
                # CustomTkinter가 시작 직후 자기 아이콘으로 덮어써서 조금 뒤에 다시 설정
                self.root.after(250, lambda: self.root.iconbitmap(str(paths.asset("app_icon.ico"))))
            if paths.asset("app_icon_256.png").exists():
                self._icon_img = tk.PhotoImage(file=str(paths.asset("app_icon_256.png")))
                self.root.iconphoto(True, self._icon_img)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        # --- 머리글
        header = ctk.CTkFrame(self.root, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=3, sticky="ew", padx=18, pady=(14, 6))
        if paths.asset("app_icon_256.png").exists():
            from PIL import Image
            logo = ctk.CTkImage(Image.open(paths.asset("app_icon_256.png")), size=(40, 40))
            ctk.CTkLabel(header, image=logo, text="").pack(side="left", padx=(0, 10))
        title = ctk.CTkFrame(header, fg_color="transparent")
        title.pack(side="left")
        ctk.CTkLabel(title, text="Mirobot Sketch", font=font(22, "bold"), anchor="w").pack(anchor="w")
        ctk.CTkLabel(title, text="사진을 로봇 팔이 그릴 수 있는 선으로", font=font(12), text_color=MUTED,
                     anchor="w").pack(anchor="w")
        self.mode = ctk.CTkSegmentedButton(header, values=["라이트", "다크"], command=self.set_mode, font=font(12))
        self.mode.set("다크" if ctk.get_appearance_mode() == "Dark" else "라이트")
        self.mode.pack(side="right")
        self.agent_btn = ctk.CTkButton(header, text="✦ 에이전트", command=self.toggle_agent, font=font(13),
                                       height=32, width=110, fg_color="transparent", border_width=1,
                                       text_color=TEXT)
        self.agent_btn.pack(side="right", padx=(0, 10))

        # --- 왼쪽 설정 패널
        side = ctk.CTkScrollableFrame(self.root, width=340, fg_color="transparent")
        side.grid(row=1, column=0, sticky="ns", padx=(18, 8), pady=(0, 18))

        c1 = Card(side, "① 이미지")
        c1.pack(fill="x", pady=(0, 10))
        ctk.CTkButton(c1, text="이미지 열기", command=self.open_image, font=font(13), height=36,
                      fg_color=ACCENT).pack(fill="x", padx=14)
        self.path_label = ctk.CTkLabel(c1, text="선택된 파일 없음", font=font(11), text_color=MUTED,
                                       wraplength=300, anchor="w", justify="left")
        self.path_label.pack(fill="x", padx=14, pady=(4, 8))
        ctk.CTkLabel(c1, text="이미지 종류 (추천 설정 적용)", font=font(12), anchor="w").pack(fill="x", padx=14)
        self.type_seg = ctk.CTkSegmentedButton(c1, values=TYPE_LABELS, command=lambda _: self.apply_type_preset(),
                                               font=font(12))
        self.type_seg.set(presets.IMAGE_TYPES["illustration"]["label"])
        self.type_seg.pack(fill="x", padx=14, pady=(4, 2))
        self.type_hint = ctk.CTkLabel(c1, text="", font=font(11), text_color=MUTED, wraplength=300,
                                      anchor="w", justify="left")
        self.type_hint.pack(fill="x", padx=14, pady=(2, 12))

        c2 = Card(side, "② 상세도와 크기")
        c2.pack(fill="x", pady=(0, 10))
        self.detail_seg = ctk.CTkSegmentedButton(c2, values=DETAIL_LABELS, command=lambda _: self.apply_detail_preset(),
                                                 font=font(12))
        self.detail_seg.set("높음")
        self.detail_seg.pack(fill="x", padx=14, pady=(2, 6))
        lim = self.cfg["limits"]["max_abs_paper_x_mm"] * 2
        plim = self.cfg["limits_pending_verification"]["max_abs_paper_x_mm"] * 2
        self.box_mm = self._slider(c2, "그리기 크기 (mm, 긴 변)", 30, plim, 100, 0, steps=int(plim - 30))
        ctk.CTkLabel(c2, text=f"파란 점선 {lim:.0f}mm = 실행기 허용 · 주황 점선 {plim:.0f}mm = 실물 확인 전",
                     font=font(11), text_color=MUTED, wraplength=300, anchor="w", justify="left"
                     ).pack(fill="x", padx=14, pady=(0, 12))

        c3 = Card(side, "③ 실행")
        c3.pack(fill="x", pady=(0, 10))
        self.run_btn = ctk.CTkButton(c3, text="처리 실행", command=self.process, font=font(14, "bold"),
                                     height=42, fg_color=ACCENT)
        self.run_btn.pack(fill="x", padx=14, pady=(2, 6))
        self.sim_btn = ctk.CTkButton(c3, text="로봇 시뮬레이션 (관절 한계)", command=self.simulate, font=font(13),
                                     height=36, fg_color="transparent", border_width=2, text_color=TEXT)
        self.sim_btn.pack(fill="x", padx=14, pady=3)
        row = ctk.CTkFrame(c3, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(3, 6))
        ctk.CTkButton(row, text="JSON 내보내기", command=self.export_strokes, font=font(12), height=32,
                      fg_color="transparent", border_width=1, text_color=TEXT
                      ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.traj_btn = ctk.CTkButton(row, text="RViz 3D로 보기", command=self.view_rviz, font=font(12), height=32,
                                      fg_color="transparent", border_width=1, text_color=TEXT, state="disabled")
        self.traj_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.progress = ctk.CTkProgressBar(c3, mode="indeterminate", height=6)
        self.progress.pack(fill="x", padx=14, pady=(6, 4))
        self.progress.set(0)
        self.status = ctk.CTkLabel(c3, text="이미지를 열어 주세요.", font=font(12), text_color=ACCENT,
                                   wraplength=300, anchor="w", justify="left")
        self.status.pack(fill="x", padx=14, pady=(0, 12))

        c4 = Card(side, "세부 조절")
        c4.pack(fill="x", pady=(0, 10))
        self.use_rembg = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(c4, text="배경 제거 (rembg, 첫 실행만 느림)", variable=self.use_rembg,
                      font=font(12)).pack(anchor="w", padx=14, pady=(2, 6))
        ctk.CTkLabel(c4, text="선 후보", font=font(12), anchor="w").pack(fill="x", padx=14)
        self.line_seg = ctk.CTkSegmentedButton(c4, values=["윤곽 (Canny)", "어두운 선 중심"], font=font(12))
        self.line_seg.set("윤곽 (Canny)")
        self.line_seg.pack(fill="x", padx=14, pady=(2, 4))
        self.canny_low = self._slider(c4, "Canny 하한", 0, 255, 30, 0)
        self.canny_high = self._slider(c4, "Canny 상한", 0, 400, 100, 0)
        self.min_len = self._slider(c4, "최소 선 덩어리 (px)", 1, 100, 8, 0, steps=99)
        self.epsilon = self._slider(c4, "단순화 오차 (px, 클수록 명령 수 감소)", 0.5, 5.0, 1.0, 1, steps=45)
        self.median = self._slider(c4, "미디언 블러 (px, 만화 망점 제거)", 0, 15, 0, 0, steps=15)
        self.dedupe = self._slider(c4, "이중선 제거 거리 (px, 0 = 끔)", 0, 8, presets.DEFAULT_DEDUPE_PX, 0, steps=8)
        self.merge = self._slider(c4, "획 이어붙이기 거리 (px, 0 = 끔)", 0, 8, presets.DEFAULT_MERGE_JOIN_PX, 0, steps=8)
        ctk.CTkFrame(c4, height=8, fg_color="transparent").pack()

        # --- 오른쪽: 미리보기 + 요약 카드
        right = ctk.CTkFrame(self.root, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 18), pady=(0, 18))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=1)

        preview = Card(right)
        preview.grid(row=0, column=0, sticky="nsew")
        self.fig = Figure(figsize=(11, 7.4))
        gs = self.fig.add_gridspec(2, 3, height_ratios=[1, 1.7])
        self.ax_in = self.fig.add_subplot(gs[0, 0])
        self.ax_edge = self.fig.add_subplot(gs[0, 1])
        self.ax_order = self.fig.add_subplot(gs[0, 2])
        self.ax_paper = self.fig.add_subplot(gs[1, :])
        self.canvas = FigureCanvasTkAgg(self.fig, master=preview)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)
        self._style_figure()
        self._placeholder()

        stats = ctk.CTkFrame(right, fg_color="transparent")
        stats.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        for i in range(4):
            stats.grid_columnconfigure(i, weight=1, uniform="stat")
        self.st_strokes = StatCard(stats, "획 / 명령")
        self.st_size = StatCard(stats, "그림 크기")
        self.st_time = StatCard(stats, "예상 시간")
        self.st_sim = StatCard(stats, "로봇 시뮬레이션")
        for i, w in enumerate((self.st_strokes, self.st_size, self.st_time, self.st_sim)):
            w.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 5, 0 if i == 3 else 5))

    def _slider(self, parent, label, lo, hi, default, digits, steps=None):
        head = ctk.CTkFrame(parent, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(6, 0))
        ctk.CTkLabel(head, text=label, font=font(12), anchor="w").pack(side="left")
        val = ctk.CTkLabel(head, text=f"{default:.{digits}f}", font=font(12, "bold"), text_color=ACCENT)
        val.pack(side="right")
        var = tk.DoubleVar(value=default)
        ctk.CTkSlider(parent, from_=lo, to=hi, variable=var, number_of_steps=steps or int(hi - lo),
                      button_color=ACCENT, progress_color=ACCENT).pack(fill="x", padx=10, pady=(2, 2))
        var.trace_add("write", lambda *_: val.configure(text=f"{var.get():.{digits}f}"))
        return var

    # ---------------------------------------------------------- 그림 테마
    def _theme_colors(self):
        dark = ctk.get_appearance_mode() == "Dark"
        return ("#1f2430", "#e5e7eb") if dark else ("#ffffff", "#111827")

    def _style_figure(self):
        bg, fg = self._theme_colors()
        self.fig.set_facecolor(bg)
        for ax in (self.ax_in, self.ax_edge, self.ax_order, self.ax_paper):
            ax.set_facecolor(bg)
            ax.title.set_color(fg)
        self.canvas.get_tk_widget().configure(bg=bg)

    def _placeholder(self):
        for ax in (self.ax_in, self.ax_edge, self.ax_order, self.ax_paper):
            ax.clear()
            ax.axis("off")
        _, fg = self._theme_colors()
        self.ax_paper.text(0.5, 0.5, "이미지를 열고 '처리 실행'을 누르면\nA4 종이 위 미리보기가 여기에 나옵니다",
                           ha="center", va="center", fontsize=13, color=fg, alpha=0.6, transform=self.ax_paper.transAxes)
        self.fig.tight_layout()
        self.canvas.draw()

    def set_mode(self, value):
        ctk.set_appearance_mode("Light" if value == "라이트" else "Dark")
        self._style_figure()
        if self.result:
            self._draw_preview(self.result)
        else:
            self._placeholder()

    # -------------------------------------------------------------- 프리셋
    def _type_key(self):
        return TYPE_KEYS[TYPE_LABELS.index(self.type_seg.get())]

    def _detail_key(self):
        return DETAIL_KEYS[DETAIL_LABELS.index(self.detail_seg.get())]

    def apply_type_preset(self):
        t = presets.IMAGE_TYPES[self._type_key()]
        self.detail_seg.set(DETAIL_LABELS[DETAIL_KEYS.index(t["detail"])])
        self.use_rembg.set(t["rembg"])
        self.median.set(t["median"])
        self.type_hint.configure(text=t["why"])
        self.apply_detail_preset()

    def apply_detail_preset(self):
        lo, hi, ml, eps = presets.DETAIL_PRESETS[self._detail_key()]
        self.canny_low.set(lo)
        self.canny_high.set(hi)
        self.min_len.set(ml)
        self.epsilon.set(eps)

    # ---------------------------------------------------------------- 동작
    def open_image(self):
        path = filedialog.askopenfilename(
            initialdir=str(paths.input_dir()),
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.jfif *.bmp *.webp")])
        if not path:
            return
        try:
            self.session.set_image(path)
        except ValueError as e:
            messagebox.showerror("오류", str(e))
            return
        self.traj_btn.configure(state="disabled")
        self.path_label.configure(text=Path(path).name)
        self._show_original()
        self._set_status("이미지 로드됨. 종류를 고르고 '처리 실행'을 누르세요.")

    def _push_controls_to_session(self):
        """화면의 선택·슬라이더 값을 세션 설정으로 옮김 (처리 실행 직전)."""
        s = self.session
        with s.lock:
            s.image_type, s.detail = self._type_key(), self._detail_key()
            s.params.update(
                canny_low=round(self.canny_low.get()), canny_high=round(self.canny_high.get()),
                min_length_px=self.min_len.get(), epsilon_px=round(self.epsilon.get(), 1),
                line_source="dark" if self.line_seg.get().startswith("어두운") else "canny",
                median_ksize=int(round(self.median.get())), dedupe_px=int(round(self.dedupe.get())),
                merge_join_px=round(self.merge.get()), rembg=bool(self.use_rembg.get()),
                box_mm=round(self.box_mm.get()))

    def _sync_controls_from_session(self):
        """에이전트가 세션 설정을 바꿨을 때 화면 선택·슬라이더를 맞춤."""
        s = self.session
        p = s.params
        self.type_seg.set(presets.IMAGE_TYPES[s.image_type]["label"])
        self.type_hint.configure(text=presets.IMAGE_TYPES[s.image_type]["why"])
        self.detail_seg.set(DETAIL_LABELS[DETAIL_KEYS.index(s.detail)])
        for var, key in ((self.canny_low, "canny_low"), (self.canny_high, "canny_high"),
                         (self.min_len, "min_length_px"), (self.epsilon, "epsilon_px"),
                         (self.median, "median_ksize"), (self.dedupe, "dedupe_px"),
                         (self.merge, "merge_join_px"), (self.box_mm, "box_mm")):
            var.set(p[key])
        self.use_rembg.set(bool(p["rembg"]))
        self.line_seg.set("어두운 선 중심" if p["line_source"] == "dark" else "윤곽 (Canny)")

    def _refresh_from_session(self, what="result"):
        self._sync_controls_from_session()
        if self.session.result is not None:
            self._show_result(self.session.result, status="에이전트가 결과를 바꿨습니다.")
        if self.session.sim:
            self._show_sim(self.session.sim["summary"])

    def agent_busy(self, busy):
        """에이전트가 작업 중이면 처리·시뮬레이션 버튼을 잠금 (같은 세션을 동시에 바꾸지 않게)."""
        self._agent_busy = busy
        state = "disabled" if busy or self.busy else "normal"
        self.run_btn.configure(state=state)
        self.sim_btn.configure(state=state)

    def _start_busy(self, text):
        self.busy = True
        self.run_btn.configure(state="disabled")
        self.sim_btn.configure(state="disabled")
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self._set_status(text)

    def _end_busy(self):
        def done():
            self.busy = False
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(0)
            state = "disabled" if self._agent_busy else "normal"
            self.run_btn.configure(state=state)
            self.sim_btn.configure(state=state)
        self._ui(done)

    def process(self):
        if self.img_path is None:
            messagebox.showwarning("알림", "먼저 이미지를 열어주세요.")
            return
        if self.busy or self._agent_busy:
            return
        self._push_controls_to_session()
        self._start_busy("처리 중...")
        threading.Thread(target=self._process_worker, daemon=True).start()

    def _process_worker(self):
        try:
            s = self.session
            if s.params.get("rembg") and (s.image_path, True) not in s._base_cache:
                self._set_status("배경 제거 중 (rembg, 한 번만 오래 걸림)...")
            else:
                self._set_status("선 추출 / 획 추적 중...")
            r = s.run()
            self._ui(self._show_result, r)
        except Exception as e:  # GUI에 오류를 보여주기 위함 (SessionError 포함)
            self._ui(messagebox.showerror, "오류", str(e))
            self._set_status("오류 발생")
        finally:
            self._end_busy()

    def _show_original(self):
        """이미지를 열자마자 컬러 원본을 입력 칸에 표시 (나머지 칸은 처리 전이라 비움)."""
        for ax in (self.ax_in, self.ax_edge, self.ax_order, self.ax_paper):
            ax.clear()
            ax.axis("off")
        _, fg = self._theme_colors()
        self.ax_in.imshow(cv2.cvtColor(self.session.color, cv2.COLOR_BGR2RGB))
        self.ax_in.set_title("입력", fontsize=11, color=fg)
        self.fig.tight_layout()
        self.canvas.draw()

    def _draw_preview(self, r):
        for ax in (self.ax_in, self.ax_edge, self.ax_order, self.ax_paper):
            ax.clear()
            ax.axis("off")
        _, fg = self._theme_colors()
        self.ax_in.imshow(cv2.cvtColor(r["color"], cv2.COLOR_BGR2RGB))   # 처리는 흑백, 표시는 컬러 원본
        self.ax_edge.imshow(255 - r["edges"], cmap="gray")
        order = sp.draw_order_preview(r["strokes_px"], r["base"].shape)
        self.ax_order.imshow(cv2.cvtColor(order, cv2.COLOR_BGR2RGB))
        self.ax_paper.imshow(cv2.cvtColor(r["paper"], cv2.COLOR_BGR2RGB))
        for ax, title in ((self.ax_in, "입력"), (self.ax_edge, "선 후보"),
                          (self.ax_order, "그리는 순서 (파랑→빨강)"),
                          (self.ax_paper, f"A4 종이 미리보기 · 펜 굵기 {self.cfg['pen'].get('line_width_mm', 0.5)}mm")):
            ax.set_title(title, fontsize=11, color=fg)
        self.fig.tight_layout()
        self.canvas.draw()

    def _show_result(self, r, status="완료. 로봇 시뮬레이션으로 관절 한계를 확인해 보세요."):
        self.traj_btn.configure(state="normal")
        self._draw_preview(r)
        t, pl = r["timing"], r["placement"]
        self.st_strokes.set(f"{t['stroke_count']}획", f"명령 {t['command_count']}개")
        size_color = BAD if r["out_of_pending"] else (WARN if r["out_of_limits"] else None)
        size_note = ("실물 미확인 범위도 초과" if r["out_of_pending"]
                     else "실행 시 --pending-limits 필요" if r["out_of_limits"] else "실행기 허용 범위 안")
        self.st_size.set(f"{pl['drawing_width_mm']:.0f}×{pl['drawing_height_mm']:.0f} mm", size_note, size_color)
        self.st_time.set(f"{t['total_s'] / 60:.1f}분",
                         f"그리기 {t['draw_s'] / 60:.1f} · 이동 {t['travel_s'] / 60:.1f} · "
                         f"펜 올림/내림 {t['pen_lift_s'] / 60:.1f} · 지연 {t['latency_s'] / 60:.1f}(가정)")
        self.st_sim.set("—", "시뮬레이션 버튼으로 검사")
        edits = len(self.session.edit_log)
        self._set_status(status + (f" (획 편집 {edits}건)" if edits else ""))

    def simulate(self):
        if not self.result:
            messagebox.showwarning("알림", "먼저 '처리 실행'을 해주세요.")
            return
        if self.busy or self._agent_busy:
            return
        path_mm = self.result["timing"]["pen_down_mm"] + self.result["timing"]["pen_up_mm"]
        self._start_busy(f"시뮬레이션 중... (경로 약 {path_mm:.0f}mm, 1mm마다 역기구학)")
        self.st_sim.set("검사 중", "")
        threading.Thread(target=self._sim_worker, daemon=True).start()

    def _sim_worker(self):
        try:
            self._ui(self._show_sim, self.session.simulate())
        except Exception as e:
            self._ui(messagebox.showerror, "시뮬레이션 오류", str(e))
        finally:
            self._end_busy()

    def _show_sim(self, summary):
        head = summary["verdict"].split(":")[0]
        color = OK if head == "PASS" else (WARN if head == "WARN" else BAD)
        self.st_sim.set(head, f"한계까지 최소 여유 {summary['min_margin_deg']:.1f}° ({summary['axis']})", color)
        self.traj_btn.configure(state="normal")
        self._set_status("시뮬레이션 완료")

    def export_strokes(self):
        if not self.result:
            messagebox.showwarning("알림", "먼저 '처리 실행'을 해주세요.")
            return
        path = filedialog.asksaveasfilename(initialdir=str(paths.output_dir()), defaultextension=".json",
                                            filetypes=[("JSON", "*.json")])
        if not path:
            return
        r = self.result
        metrics = sp.stroke_metrics(r["strokes_mm"], start=(0.0, 0.0))
        metrics["estimated_time"] = r["timing"]
        source = {
            "image": r["path"],
            "image_size_px": [int(r["base"].shape[1]), int(r["base"].shape[0])],
            "params": {**r["params"], "type": self._type_key(), "detail": self._detail_key(), "tool": "gui_sketch"},
        }
        pm.save_strokes_json(path, pm.build_strokes_document(r["strokes_mm"], r["placement"], metrics, source))
        extra = " --pending-limits" if r["out_of_limits"] else ""
        messagebox.showinfo("완료", f"저장됨: {path}\n\n다음: python robot/draw_executor.py \"{path}\"{extra}")

    def view_rviz(self):
        """시뮬레이션(아직이면 먼저 실행) → 관절 궤적 저장 → WSL에서 RViz 재생 창 열기."""
        if not self.result:
            messagebox.showwarning("알림", "먼저 '처리 실행'을 해주세요.")
            return
        if self.busy or self._agent_busy:
            return
        self._start_busy("RViz 준비 중..." if self.sim_result else "시뮬레이션 후 RViz를 엽니다...")
        self.traj_btn.configure(state="disabled")
        threading.Thread(target=self._rviz_worker, daemon=True).start()

    def _rviz_worker(self):
        from . import mirobot_sim as ms
        from . import rviz_launch
        try:
            if not self.sim_result:
                self._ui(self._show_sim, self.session.simulate())
            traj_path = paths.output_dir() / "rviz_traj.json"
            doc = ms.trajectory_doc(self.sim_result, self.cfg, Path(self.result["path"]).name)
            traj_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            self._set_status("WSL에서 RViz를 여는 중... (처음엔 10~20초 걸릴 수 있음)")
            self._rviz_proc = rviz_launch.launch(traj_path, speed=20)
            self._set_status(f"RViz 창에서 20배속으로 반복 재생합니다. 창을 닫으면 멈춥니다.\n궤적: {traj_path}")
        except rviz_launch.RvizUnavailable as e:
            self._set_status("RViz를 열 수 없습니다.")
            self._ui(messagebox.showinfo, "RViz 3D 보기", str(e))
        except Exception as e:
            self._ui(messagebox.showerror, "RViz 오류", str(e))
        finally:
            self._end_busy()
            self._ui(lambda: self.traj_btn.configure(state="normal" if self.result else "disabled"))

    def _set_status(self, text):
        self._ui(lambda: self.status.configure(text=text))

    # ---------------------------------------------------------------- 에이전트
    def _init_agent(self):
        """오른쪽 에이전트 패널과 CLI용 로컬 브리지. 실패해도 앱의 나머지 기능은 그대로 동작."""
        self.agent_panel = self.bridge = None
        self._agent_visible = False
        try:
            from .agent.bridge import BridgeServer
            from .agent.panel import AgentPanel
            from .agent.tools import AgentToolbox
        except ImportError as e:
            self.agent_btn.configure(state="disabled", text=f"에이전트 없음 ({e.name})")
            return
        self.toolbox = AgentToolbox(self.session, on_change=lambda what: self._ui(self._refresh_from_session, what))
        self.bridge = BridgeServer(self.toolbox).start()
        icon = None
        if paths.asset("app_icon_256.png").exists():
            from PIL import Image
            icon = ctk.CTkImage(Image.open(paths.asset("app_icon_256.png")), size=(26, 26))
        self.agent_panel = AgentPanel(self.root, self, self.toolbox, self.bridge, font, icon_image=icon,
                                      on_close=self.toggle_agent)

    def toggle_agent(self):
        if self.agent_panel is None:
            return
        self._agent_visible = not self._agent_visible
        if self._agent_visible:
            self.agent_panel.grid(row=1, column=2, sticky="ns", padx=(0, 18), pady=(0, 18))
            self.agent_btn.configure(fg_color=ACCENT, text_color="#ffffff")
        else:
            self.agent_panel.grid_remove()
            self.agent_btn.configure(fg_color="transparent", text_color=TEXT)

    def _on_close(self):
        if self.agent_panel is not None:
            for b in self.agent_panel.backends.values():
                b.cancel()
        if self.bridge is not None:
            self.bridge.stop()
        self.root.destroy()


APP_ID = "YoobinKim.MirobotSketch"  # 작업표시줄 묶음·고정용 앱 ID (바로가기/설치 프로그램과 같은 값)


def main():
    if sys.platform.startswith("win"):
        # 파이썬으로 실행해도 작업표시줄에 python 아이콘이 아니라 이 앱 아이콘으로 따로 표시되게 함
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError, OSError):
            pass
    ctk.set_appearance_mode("Light")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    SketchApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
