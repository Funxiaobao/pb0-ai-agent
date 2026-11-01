"""抓屏：mss 后端（本机 Python 3.12 无 dxcam 轮子，且为核显，mss 足够 30fps）。

永远只保留最新一帧，抓屏线程不阻塞决策。接口与 dxcam 版保持一致：
ScreenCapture(region=[x1,y1,x2,y2] 或 None, fps=30).latest() -> BGR ndarray
"""
import threading
import time

import numpy as np
import mss


class ScreenCapture:
    def __init__(self, region=None, fps=30, warmup=0.5):
        self.region = None
        if region and region != "auto":
            x1, y1, x2, y2 = [int(v) for v in region]
            self.region = {"left": x1, "top": y1, "width": x2 - x1, "height": y2 - y1}
        self.fps = max(5, int(fps))
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._sct = mss.mss()
        f = self._grab()
        if f is None:
            raise RuntimeError("mss 抓屏失败")
        with self._lock:
            self._frame = f
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _grab(self):
        try:
            shot = self._sct.grab(self.region if self.region else self._sct.monitors[1])
            arr = np.asarray(shot, dtype=np.uint8)[:, :, :3]  # BGRA
            return np.ascontiguousarray(arr[:, :, ::-1])      # -> BGR
        except Exception:
            return None

    def _loop(self):
        period = 1.0 / self.fps
        while not self._stop.is_set():
            f = self._grab()
            if f is not None:
                with self._lock:
                    self._frame = f
            time.sleep(period * 0.5)

    def latest(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self):
        self._stop.set()
        try:
            self._sct.close()
        except Exception:
            pass


if __name__ == "__main__":
    c = ScreenCapture()
    time.sleep(1)
    f = c.latest()
    print("frame:", None if f is None else f.shape)
    c.stop()
