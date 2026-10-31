"""DXGI 抓屏：永远只保留最新一帧，抓屏线程不阻塞决策。"""
import threading
import time

import dxcam


class ScreenCapture:
    def __init__(self, region=None, fps=30, warmup=1.0):
        self.region = tuple(region) if region else None
        self.cam = dxcam.create(output_color="BGR")
        if self.cam is None:
            raise RuntimeError("dxcam 初始化失败：检查是否装了 dxcam、显卡驱动是否正常")
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.cam.start(region=self.region, target_fps=fps)
        # 前几帧经常是黑的，先丢一会儿
        t0 = time.time()
        while time.time() - t0 < warmup:
            f = self.cam.get_latest_frame()
            if f is not None:
                with self._lock:
                    self._frame = f
            time.sleep(0.02)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            f = self.cam.get_latest_frame()
            if f is not None:
                with self._lock:
                    self._frame = f
            else:
                time.sleep(0.005)

    def latest(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self):
        self._stop.set()
        try:
            self.cam.stop()
        except Exception:
            pass


if __name__ == "__main__":
    c = ScreenCapture()
    time.sleep(1)
    f = c.latest()
    print("frame:", None if f is None else f.shape)
    c.stop()
