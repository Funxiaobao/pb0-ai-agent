"""按键握手测试：先测基线帧差，再发 点击+跳跃，测画面是否因输入变化。"""
import sys
import time

import numpy as np

sys.path.insert(0, ".")

from playwright.sync_api import sync_playwright
from agent.capture import ScreenCapture


def main():
    cap = ScreenCapture(region=None, fps=30)

    def shot():
        for _ in range(6):
            f = cap.latest()
            if f is not None:
                return f
            time.sleep(0.05)
        return None

    with sync_playwright() as pw:
        b = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
        pages = []
        for c in b.contexts:
            pages.extend(c.pages)
        page = None
        for p in pages:
            if "cg.163.com" in (p.url or ""):
                page = p
                break
        page.bring_to_front()
        time.sleep(0.5)

        a0 = shot()
        time.sleep(0.5)
        a1 = shot()
        base = float(np.abs(a0.astype(int) - a1.astype(int)).mean()) if (a0 is not None and a1 is not None) else -1
        print("基线帧差(无输入): %.1f" % base)

        page.mouse.click(640, 400)
        time.sleep(0.25)
        page.keyboard.down("Space")
        time.sleep(0.08)
        page.keyboard.up("Space")
        time.sleep(0.6)
        bshot = shot()
        after = float(np.abs(a1.astype(int) - bshot.astype(int)).mean()) if bshot is not None else -1
        print("输入后帧差: %.1f" % after)
        print(">>> 判定: 输入后帧差明显大于基线 -> CDP 输入通路正常" if after > base + 3 and after > 3 else ">>> 判定: 画面无额外变化, 需人工确认")
    cap.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
