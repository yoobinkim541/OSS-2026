"""
사진 -> 스케치 -> 로봇용 획(stroke) 데이터 추출 GUI
======================================================
로봇 없이 이미지 처리 파이프라인을 조절해 보고, 결과를 종이 좌표(mm)
JSON으로 저장합니다. 저장한 JSON은 그대로 robot/draw_executor.py에 넣습니다.

    python CV/gui_sketch.py
    python robot/draw_executor.py <저장한.json>            (dry-run)
    python robot/draw_executor.py <저장한.json> --execute  (실제 드로잉)

처리 로직은 sketch_pipeline.py / paper_mapping.py에 있고, 명령줄 버전은
make_strokes.py 입니다.

필요한 패키지: requirements.txt 참고 (tkinter는 파이썬 기본 포함)
"""

import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper_mapping as pm  # noqa: E402
import sketch_pipeline as sp  # noqa: E402
from make_strokes import estimate_time_s  # noqa: E402

DRAW_FEED = 300.0    # 시간 추정용 (robot/drawing_config.json과 맞출 것)
TRAVEL_FEED = 600.0


class SketchApp:
    def __init__(self, root):
        self.root = root
        self.root.title("사진 -> 로봇 드로잉 스케치 변환기")
        self.root.geometry("1400x780")

        self.img_path = None
        self.gray_original = None
        self.bg_removed = None  # rembg 결과 캐시 (느린 연산이라 따로 보관)
        self.base_img = None
        self.strokes_px = []

        self._build_ui()

    # ---- UI 구성 ----

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        controls = ttk.Frame(main, width=290)
        controls.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        ttk.Button(controls, text="이미지 열기", command=self.open_image).pack(fill=tk.X, pady=4)
        self.path_label = ttk.Label(controls, text="선택된 파일 없음", wraplength=270)
        self.path_label.pack(fill=tk.X, pady=(0, 8))

        self.use_rembg_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            controls, text="배경 제거 사용 (rembg, 선택·느림)", variable=self.use_rembg_var
        ).pack(anchor=tk.W)

        ttk.Label(controls, text="선 후보").pack(anchor=tk.W, pady=(8, 0))
        self.line_source = tk.StringVar(value="canny")
        ttk.Radiobutton(controls, text="사진 윤곽 (Canny)", value="canny",
                        variable=self.line_source).pack(anchor=tk.W)
        ttk.Radiobutton(controls, text="선화 중심선 (어두운 선)", value="dark",
                        variable=self.line_source).pack(anchor=tk.W)

        ttk.Label(controls, text="획 추출 방법").pack(anchor=tk.W, pady=(8, 0))
        self.method = tk.StringVar(value="skeleton")
        ttk.Radiobutton(controls, text="중심선 추적 (선을 한 번만 그림)", value="skeleton",
                        variable=self.method).pack(anchor=tk.W)
        ttk.Radiobutton(controls, text="findContours (비교용, 선이 두 번 그려짐)", value="contour",
                        variable=self.method).pack(anchor=tk.W)

        self.canny_low = self._add_slider(controls, "Canny 하한", 0, 255, 50)
        self.canny_high = self._add_slider(controls, "Canny 상한", 0, 400, 150)
        self.min_len = self._add_slider(controls, "최소 선 덩어리 크기(px)", 1, 100, 15)
        self.epsilon = self._add_slider(controls, "단순화 정도(px)", 0.5, 8.0, 2.0, digits=1)
        self.box_mm = self._add_slider(controls, "그리기 크기(mm, 긴 변)", 30, 100, 100)

        ttk.Button(controls, text="처리 실행", command=self.process).pack(fill=tk.X, pady=(14, 4))
        self.status_label = ttk.Label(controls, text="", foreground="blue", wraplength=270)
        self.status_label.pack(fill=tk.X, pady=4)

        self.stats_label = ttk.Label(controls, text="", wraplength=270, justify=tk.LEFT)
        self.stats_label.pack(fill=tk.X, pady=8)

        ttk.Button(
            controls, text="획 데이터 내보내기 (종이 mm JSON)", command=self.export_strokes
        ).pack(fill=tk.X, pady=4)

        preview = ttk.Frame(main)
        preview.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.fig = Figure(figsize=(11, 6))
        self.axes = [self.fig.add_subplot(1, 4, i + 1) for i in range(4)]
        for ax in self.axes:
            ax.axis("off")

        self.canvas = FigureCanvasTkAgg(self.fig, master=preview)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _add_slider(self, parent, label, lo, hi, default, digits=0):
        ttk.Label(parent, text=label).pack(anchor=tk.W, pady=(6, 0))
        var = tk.DoubleVar(value=default)
        ttk.Scale(parent, from_=lo, to=hi, variable=var, orient=tk.HORIZONTAL).pack(fill=tk.X)
        value_label = ttk.Label(parent, text=f"{default:.{digits}f}")
        value_label.pack(anchor=tk.E)
        var.trace_add("write", lambda *_: value_label.config(text=f"{var.get():.{digits}f}"))
        return var

    # ---- 동작 ----

    def open_image(self):
        path = filedialog.askopenfilename(
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.jfif *.bmp *.webp")]
        )
        if not path:
            return
        try:
            self.gray_original = sp.load_gray(path)
        except ValueError as e:
            messagebox.showerror("오류", str(e))
            return
        self.img_path = path
        self.path_label.config(text=path)
        self.bg_removed = None  # 새 이미지니 캐시 초기화
        self.status_label.config(text="이미지 로드됨. '처리 실행'을 눌러주세요.")

    def process(self):
        if self.img_path is None:
            messagebox.showwarning("알림", "먼저 이미지를 열어주세요.")
            return
        self.status_label.config(text="처리 중...")
        # rembg는 느리므로 별도 스레드에서 실행해 GUI가 멈추지 않도록 함
        params = dict(
            canny_low=self.canny_low.get(), canny_high=self.canny_high.get(),
            min_length_px=self.min_len.get(), epsilon_px=self.epsilon.get(),
            method=self.method.get(), line_source=self.line_source.get(),
        )
        threading.Thread(target=self._process_worker, args=(params, self.use_rembg_var.get()),
                         daemon=True).start()

    def _process_worker(self, params, use_rembg):
        try:
            if use_rembg:
                if self.bg_removed is None:
                    self._set_status("배경 제거 중 (rembg)...")
                    self.bg_removed = sp.remove_background(self.img_path)
                base_img = self.bg_removed
            else:
                base_img = self.gray_original

            self._set_status("선 추출 / 획 추적 중...")
            edges, strokes = sp.run_pipeline(base_img, **params)
            self.root.after(0, self._update_preview, base_img, edges, strokes, params)
        except Exception as e:  # GUI에 오류를 보여주기 위함
            msg = str(e)
            self.root.after(0, lambda: messagebox.showerror("오류", msg))
            self._set_status("오류 발생")

    def _set_status(self, text):
        self.root.after(0, lambda: self.status_label.config(text=text))

    def _update_preview(self, base_img, edges, strokes, params):
        self.base_img = base_img
        self.strokes_px = strokes
        self.params = params

        for ax in self.axes:
            ax.clear()
            ax.axis("off")
        self.axes[0].imshow(base_img, cmap="gray")
        self.axes[0].set_title("Input", fontsize=10)
        self.axes[1].imshow(255 - edges, cmap="gray")
        self.axes[1].set_title("Line candidates", fontsize=10)
        self.axes[2].imshow(255 - sp.draw_strokes_image(strokes, base_img.shape), cmap="gray")
        self.axes[2].set_title(f"Strokes ({len(strokes)})", fontsize=10)
        order = sp.draw_order_preview(strokes, base_img.shape)
        self.axes[3].imshow(cv2.cvtColor(order, cv2.COLOR_BGR2RGB))
        self.axes[3].set_title("Order (blue->red, gray=pen-up)", fontsize=10)
        self.canvas.draw()

        if not strokes:
            self.status_label.config(text="획이 없습니다. 임계값을 낮춰보세요.")
            self.stats_label.config(text="")
            return
        box = self.box_mm.get()
        strokes_mm, placement = pm.pixels_to_paper(strokes, box_mm=(box, box))
        m = sp.stroke_metrics(strokes_mm, start=(0.0, 0.0))
        t = estimate_time_s(m, DRAW_FEED, TRAVEL_FEED)
        self.status_label.config(text="완료")
        self.stats_label.config(text=(
            f"획 개수: {m['stroke_count']}\n"
            f"총 점 개수: {m['point_count']}\n"
            f"그림 크기: {placement['drawing_width_mm']:.0f} x {placement['drawing_height_mm']:.0f} mm\n"
            f"펜다운 길이: {m['pen_down_length']:.0f} mm\n"
            f"펜업 이동: {m['pen_up_length']:.0f} mm\n"
            f"이론상 최소 시간: {t:.0f} s"
        ))

    def export_strokes(self):
        if not self.strokes_px:
            messagebox.showwarning("알림", "먼저 '처리 실행'으로 획 데이터를 만들어주세요.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        box = self.box_mm.get()
        strokes_mm, placement = pm.pixels_to_paper(self.strokes_px, box_mm=(box, box))
        metrics = sp.stroke_metrics(strokes_mm, start=(0.0, 0.0))
        metrics["estimated_min_time_s"] = round(estimate_time_s(metrics, DRAW_FEED, TRAVEL_FEED), 1)
        source = {
            "image": self.img_path,
            "image_size_px": [int(self.base_img.shape[1]), int(self.base_img.shape[0])],
            "params": {**self.params, "rembg": self.use_rembg_var.get(), "box_mm": box, "tool": "gui_sketch"},
        }
        pm.save_strokes_json(path, pm.build_strokes_document(strokes_mm, placement, metrics, source))
        messagebox.showinfo("완료", f"저장됨: {path}\n\n다음: python robot/draw_executor.py \"{path}\"")


def main():
    root = tk.Tk()
    SketchApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
