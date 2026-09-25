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
import numpy as np
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
        self.img_path = None
        self.base_cache = {}      # (경로, rembg) -> 회색조 이미지
        self.result = None        # 마지막 처리 결과 dict
        self.sim_result = None
        self.busy = False
        # 작업 스레드 -> 화면: Tkinter는 스레드에 안전하지 않으므로 작업 스레드는 큐에
        # 할 일만 넣고, 메인 스레드가 주기적으로 꺼내 실행한다.
        self._ui_queue = queue.Queue()

        self._build_ui()
        self.apply_type_preset()
        self._poll_ui_queue()

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
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=18, pady=(14, 6))
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
        self.traj_btn = ctk.CTkButton(row, text="RViz 궤적 저장", command=self.export_traj, font=font(12), height=32,
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
            gray = sp.load_gray(path)
        except ValueError as e:
            messagebox.showerror("오류", str(e))
            return
        self.img_path = path
        self.base_cache = {(path, False): gray}
        self.result = self.sim_result = None
        self.traj_btn.configure(state="disabled")
        self.path_label.configure(text=Path(path).name)
        self._set_status("이미지 로드됨. 종류를 고르고 '처리 실행'을 누르세요.")

    def _params(self):
        return dict(
            canny_low=self.canny_low.get(), canny_high=self.canny_high.get(), blur_ksize=5,
            min_length_px=self.min_len.get(), epsilon_px=self.epsilon.get(),
            line_source="dark" if self.line_seg.get().startswith("어두운") else "canny",
            median_ksize=int(round(self.median.get())),
            dedupe_px=int(round(self.dedupe.get())), merge_join_px=round(self.merge.get()),
        )

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
            self.run_btn.configure(state="normal")
            self.sim_btn.configure(state="normal")
        self._ui(done)

    def process(self):
        if self.img_path is None:
            messagebox.showwarning("알림", "먼저 이미지를 열어주세요.")
            return
        if self.busy:
            return
        self._start_busy("처리 중...")
        args = (self.img_path, self.use_rembg.get(), self._params(), round(self.box_mm.get()))
        threading.Thread(target=self._process_worker, args=args, daemon=True).start()

    def _process_worker(self, path, rembg, params, box):
        try:
            key = (path, rembg)
            if key not in self.base_cache:
                self._set_status("배경 제거 중 (rembg, 한 번만 오래 걸림)...")
                self.base_cache[key] = sp.remove_background(path, cache_dir=paths.cache_dir())
            base = self.base_cache[key]
            self._set_status("선 추출 / 획 추적 중...")
            edges, strokes_px = sp.run_pipeline(base, **params)
            if not strokes_px:
                raise ValueError("획이 없습니다. 상세도를 높이거나 Canny 하한을 낮춰보세요.")
            strokes_mm, placement = pm.pixels_to_paper(strokes_px, box_mm=(box, box))
            strokes_list = [[tuple(p) for p in s] for s in strokes_mm]
            timing = de.estimate_time(strokes_list, self.cfg)
            lim = self.cfg["limits"]["max_abs_paper_x_mm"]
            plim = self.cfg["limits_pending_verification"]["max_abs_paper_x_mm"]
            paper = pm.render_paper_preview(strokes_mm, self.cfg["pen"].get("line_width_mm", 0.5),
                                            4.0, limit_mm=lim, pending_limit_mm=plim)
            result = dict(base=base, edges=edges, strokes_px=strokes_px, strokes_mm=strokes_mm,
                          placement=placement, timing=timing, params={**params, "rembg": rembg, "box_mm": box},
                          paper=paper, path=path,
                          out_of_limits=len(de.check_limits(strokes_list, self.cfg)),
                          out_of_pending=len(de.check_limits(strokes_list, self.cfg, pending=True)))
            self._ui(self._show_result, result)
        except Exception as e:  # GUI에 오류를 보여주기 위함
            self._ui(messagebox.showerror, "오류", str(e))
            self._set_status("오류 발생")
        finally:
            self._end_busy()

    def _draw_preview(self, r):
        for ax in (self.ax_in, self.ax_edge, self.ax_order, self.ax_paper):
            ax.clear()
            ax.axis("off")
        _, fg = self._theme_colors()
        self.ax_in.imshow(r["base"], cmap="gray")
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

    def _show_result(self, r):
        self.result, self.sim_result = r, None
        self.traj_btn.configure(state="disabled")
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
        self._set_status("완료. 로봇 시뮬레이션으로 관절 한계를 확인해 보세요.")

    def simulate(self):
        if not self.result:
            messagebox.showwarning("알림", "먼저 '처리 실행'을 해주세요.")
            return
        if self.busy:
            return
        strokes = [[tuple(p) for p in s] for s in self.result["strokes_mm"]]
        path_mm = self.result["timing"]["pen_down_mm"] + self.result["timing"]["pen_up_mm"]
        self._start_busy(f"시뮬레이션 중... (경로 약 {path_mm:.0f}mm, 1mm마다 역기구학)")
        self.st_sim.set("검사 중", "")
        threading.Thread(target=self._sim_worker, args=(strokes,), daemon=True).start()

    def _sim_worker(self, strokes):
        try:
            from . import mirobot_sim as ms
            res = ms.simulate(ms.plan_targets(strokes, self.cfg))
            self._ui(self._show_sim, res, ms.verdict(res))
        except Exception as e:
            self._ui(messagebox.showerror, "시뮬레이션 오류", str(e))
        finally:
            self._end_busy()

    def _show_sim(self, res, verdict):
        from . import mirobot_sim as ms
        self.sim_result = res
        j = int(np.argmin(res["min_margin_deg"]))
        head = verdict.split(":")[0]
        color = OK if head == "PASS" else (WARN if head == "WARN" else BAD)
        self.st_sim.set(head, f"한계까지 최소 여유 {res['min_margin_deg'][j]:.1f}° ({ms.CONTROLLER_AXES[j]})", color)
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

    def export_traj(self):
        if not self.sim_result:
            return
        from . import mirobot_sim as ms
        path = filedialog.asksaveasfilename(initialdir=str(paths.output_dir()), defaultextension=".json",
                                            initialfile="traj.json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        tip = ms.pen_tip_offset(self.cfg)
        traj = {
            "joint_names": ms.JOINT_NAMES, "units": "rad", "step_mm": 1.0, "source": self.result["path"],
            "pen_tip_offset_mm": tip.tolist(),
            "points": [{"q": [round(float(v), 5) for v in s[0]], "tcp_mm": [round(float(v), 3) for v in s[1]],
                        "pen_tip_mm": [round(float(v), 3) for v in s[1] + tip],
                        "pen_down": bool(s[3]), "command": s[2]} for s in self.sim_result["samples"]],
        }
        Path(path).write_text(json.dumps(traj, ensure_ascii=False), encoding="utf-8")
        wsl = "/mnt/" + path[0].lower() + path[2:].replace("\\", "/") if path[1] == ":" else path
        messagebox.showinfo("완료", f"저장됨: {path}\n\nWSL에서 재생:\nbash sim/run_rviz.sh \"{wsl}\" 20")

    def _set_status(self, text):
        self._ui(lambda: self.status.configure(text=text))


def main():
    ctk.set_appearance_mode("Light")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    SketchApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
