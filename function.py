from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from io import BytesIO
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageTk

import tkinter as tk
from tkinter import ttk, messagebox, filedialog


Point = Tuple[int, int]
ROI = Tuple[int, int, int, int]  # x1, y1, x2, y2


def clamp_roi(roi: ROI) -> ROI:
    x1, y1, x2, y2 = roi
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return int(x1), int(y1), int(x2), int(y2)


def inside_circle(p: Point, center: Point, radius: int) -> bool:
    dx = p[0] - center[0]
    dy = p[1] - center[1]
    return dx * dx + dy * dy <= radius * radius


class Settings:
    def __init__(self, path: str):
        self.path = path
        self.data: Dict = {}
        self.load()

    def load(self) -> None:
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        else:
            self.data = {}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get(self, *keys, default=None):
        cur = self.data
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    def set(self, value, *keys) -> None:
        cur = self.data
        for k in keys[:-1]:
            if k not in cur or not isinstance(cur[k], dict):
                cur[k] = {}
            cur = cur[k]
        cur[keys[-1]] = value


class AdbClient:
    def __init__(self, adb_path: str):
        self.adb_path = adb_path

    def _run(self, args: List[str], timeout_s: float = 10.0) -> str:
        cmd = [self.adb_path] + args
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_s,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return p.stdout.strip()

    def list_devices(self) -> List[str]:
        out = self._run(["devices"], timeout_s=10.0)
        serials: List[str] = []
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serials.append(parts[0])
        return serials

    def connect(self, host: str, port: int) -> str:
        return self._run(["connect", f"{host}:{port}"], timeout_s=6.0)

    def disconnect(self, serial: str) -> str:
        return self._run(["disconnect", serial], timeout_s=6.0)

    def screenshot(self, serial: str) -> Image.Image:
        cmd = [self.adb_path, "-s", serial, "exec-out", "screencap", "-p"]
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15.0,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if p.returncode != 0 or not p.stdout:
            raise RuntimeError((p.stderr or b"").decode("utf-8", "replace"))
        img = Image.open(BytesIO(p.stdout)).convert("RGB")
        return img

    def tap_hold(self, serial: str, x: int, y: int, hold_ms: int) -> None:
        hold_ms = max(1, int(hold_ms))
        # input swipe x y x y duration_ms behaves like press+hold
        self._run(["-s", serial, "shell", "input", "swipe", str(x), str(y), str(x), str(y), str(hold_ms)], timeout_s=10.0)


@dataclass
class MatchResult:
    found: bool
    score: float
    center: Optional[Point] = None
    rect: Optional[ROI] = None


class ImageMatcher:
    def __init__(self):
        self._cache: Dict[str, np.ndarray] = {}

    def _load_template(self, path: str) -> np.ndarray:
        if path in self._cache:
            return self._cache[path]
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"Không đọc được template: {path}")
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        self._cache[path] = gray
        return gray

    def match(
        self,
        screenshot_rgb: Image.Image,
        template_path: str,
        threshold: float,
        roi: Optional[ROI] = None,
    ) -> MatchResult:
        img = np.array(screenshot_rgb)[:, :, ::-1]  # RGB->BGR
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        x1, y1, x2, y2 = (0, 0, gray.shape[1], gray.shape[0])
        if roi:
            x1, y1, x2, y2 = clamp_roi(roi)
            x1 = max(0, min(x1, gray.shape[1] - 1))
            x2 = max(1, min(x2, gray.shape[1]))
            y1 = max(0, min(y1, gray.shape[0] - 1))
            y2 = max(1, min(y2, gray.shape[0]))
        crop = gray[y1:y2, x1:x2]
        tmpl = self._load_template(template_path)
        if crop.shape[0] < tmpl.shape[0] or crop.shape[1] < tmpl.shape[1]:
            return MatchResult(found=False, score=0.0)
        res = cv2.matchTemplate(crop, tmpl, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
        score = float(max_val)
        if score < float(threshold):
            return MatchResult(found=False, score=score)
        top_left = (max_loc[0] + x1, max_loc[1] + y1)
        h, w = tmpl.shape[:2]
        rect = (top_left[0], top_left[1], top_left[0] + w, top_left[1] + h)
        center = (top_left[0] + w // 2, top_left[1] + h // 2)
        return MatchResult(found=True, score=score, center=center, rect=rect)


class ScreenshotSelector(tk.Toplevel):
    def __init__(self, master: tk.Tk, image: Image.Image, title: str):
        super().__init__(master)
        self.title(title)
        self.resizable(True, True)
        self.image_orig = image

        self._scale = 1.0
        self._tk_img: Optional[ImageTk.PhotoImage] = None
        self._start: Optional[Point] = None
        self._rect_id: Optional[int] = None
        self.result_roi: Optional[ROI] = None
        self.result_crop: Optional[Image.Image] = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        frame = ttk.Frame(self)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(frame, bg="#111111", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        btns = ttk.Frame(self)
        btns.grid(row=1, column=0, sticky="ew", padx=8, pady=8)
        btns.columnconfigure(0, weight=1)

        self.lbl = ttk.Label(btns, text="Kéo chuột để chọn vùng (ROI).")
        self.lbl.grid(row=0, column=0, sticky="w")
        ttk.Button(btns, text="Hủy", command=self._cancel).grid(row=0, column=1, sticky="e", padx=(8, 0))
        ttk.Button(btns, text="OK", command=self._ok).grid(row=0, column=2, sticky="e", padx=(8, 0))

        self._render()
        self._bind()

        self.grab_set()
        self.focus_set()

    def _render(self) -> None:
        max_w, max_h = 900, 520
        w, h = self.image_orig.size
        scale = min(max_w / w, max_h / h, 1.0)
        self._scale = scale
        disp = self.image_orig.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        self._tk_img = ImageTk.PhotoImage(disp)
        self.canvas.delete("all")
        self.canvas.config(width=disp.size[0], height=disp.size[1])
        self.canvas.create_image(0, 0, anchor="nw", image=self._tk_img)

    def _bind(self) -> None:
        self.canvas.bind("<Button-1>", self._on_down)
        self.canvas.bind("<B1-Motion>", self._on_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_up)

    def _on_down(self, e) -> None:
        self._start = (e.x, e.y)
        if self._rect_id:
            self.canvas.delete(self._rect_id)
            self._rect_id = None

    def _on_move(self, e) -> None:
        if not self._start:
            return
        x0, y0 = self._start
        x1, y1 = e.x, e.y
        if self._rect_id:
            self.canvas.coords(self._rect_id, x0, y0, x1, y1)
        else:
            self._rect_id = self.canvas.create_rectangle(x0, y0, x1, y1, outline="#00ff88", width=2)

    def _on_up(self, e) -> None:
        if not self._start:
            return
        x0, y0 = self._start
        x1, y1 = e.x, e.y
        self._start = None

        # Convert to original coordinates
        ox0, oy0 = int(x0 / self._scale), int(y0 / self._scale)
        ox1, oy1 = int(x1 / self._scale), int(y1 / self._scale)
        roi = clamp_roi((ox0, oy0, ox1, oy1))
        if roi[2] - roi[0] < 3 or roi[3] - roi[1] < 3:
            self.result_roi = None
            self.result_crop = None
            self.lbl.config(text="Vùng chọn quá nhỏ, chọn lại.")
            return
        self.result_roi = roi
        self.result_crop = self.image_orig.crop(roi)
        self.lbl.config(text=f"Đã chọn ROI: {roi}")

    def _cancel(self) -> None:
        self.result_roi = None
        self.result_crop = None
        self.destroy()

    def _ok(self) -> None:
        if not self.result_roi:
            messagebox.showwarning("Chưa chọn", "Bạn chưa chọn ROI.")
            return
        self.destroy()


def resolve_path(p: str) -> str:
    p = p.replace("/", os.sep)
    if os.path.isabs(p):
        return p
    base = os.path.abspath(os.getcwd())
    return os.path.abspath(os.path.join(base, p))


def safe_sleep(stop_event, seconds: float) -> bool:
    # True if stopped early
    if seconds <= 0:
        return stop_event.is_set()
    end = time.time() + seconds
    while time.time() < end:
        if stop_event.is_set():
            return True
        time.sleep(min(0.05, end - time.time()))
    return stop_event.is_set()

