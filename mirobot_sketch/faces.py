"""
얼굴 검출과 얼굴 중심 구도
==========================
OpenCV YuNet(FaceDetectorYN)으로 실사 사진의 얼굴을 찾습니다. 모델 파일은 패키지에 들어 있습니다
(data/face_detection_yunet_2023mar.onnx, MIT, opencv_zoo). 애니·만화 그림체는 거의 잡히지 않으며,
모델이 없거나 OpenCV에 검출기가 없거나 오류가 나면 "얼굴 없음"([])으로 동작합니다.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from . import paths

MODEL_PATH = paths.asset("face_detection_yunet_2023mar.onnx")
DETECT_SIDE = 800           # 이 크기로 줄여서 검출 (좌표는 원래 크기로 되돌림)
MIN_FACE_FRACTION = 0.03    # 얼굴 폭이 짧은 변의 이 비율 미만이면 무시 (무대 조명 등 오검출)


@dataclass
class Face:
    box: np.ndarray         # (x, y, w, h)
    landmarks: np.ndarray   # 5×2: 오른눈, 왼눈, 코, 오른 입꼬리, 왼 입꼬리
    score: float

    def scaled(self, k, dx=0.0, dy=0.0):
        """좌표를 p*k + (dx, dy)로 옮긴 새 Face (크기는 k배)."""
        x, y, w, h = self.box
        return Face(np.array([x * k + dx, y * k + dy, w * k, h * k]),
                    self.landmarks * k + (dx, dy), self.score)


def _yunet(img, min_score):
    """YuNet 원시 결과 (N×15 또는 None)."""
    det = cv2.FaceDetectorYN.create(str(MODEL_PATH), "", (img.shape[1], img.shape[0]), min_score, 0.3, 50)
    return det.detect(img)[1]


def _quiet():
    """OpenCV 5의 dnn 안내 경고를 잠시 끔. (복구 함수를 돌려줌)"""
    try:
        lg = cv2.utils.logging
        old = lg.getLogLevel()
        lg.setLogLevel(lg.LOG_LEVEL_ERROR)
        return lambda: lg.setLogLevel(old)
    except Exception:
        return lambda: None


def detect_faces(bgr, min_score=0.7, detector=None):
    """얼굴 목록 (신뢰도 높은 순, 좌표는 bgr 기준). 실패하면 []."""
    h, w = bgr.shape[:2]
    s = min(1.0, DETECT_SIDE / max(h, w))
    small = cv2.resize(bgr, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA) \
        if s < 1 else bgr
    restore = _quiet()
    try:
        if detector is None:
            if not MODEL_PATH.exists() or not hasattr(cv2, "FaceDetectorYN"):
                return []
            rows = _yunet(small, min_score)
        else:
            rows = detector(small)
    except Exception:
        return []
    finally:
        restore()
    out = []
    for r in ([] if rows is None else np.asarray(rows, np.float64)):
        f = Face(r[:4].copy(), r[4:14].reshape(5, 2).copy(), float(r[14])).scaled(1 / s)
        if f.score >= min_score and f.box[2] >= MIN_FACE_FRACTION * min(h, w):
            out.append(f)
    return sorted(out, key=lambda f: -f.score)
