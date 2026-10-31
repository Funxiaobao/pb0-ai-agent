"""验证抓屏：存一张图，必须能看清游戏画面。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import yaml

from agent.capture import ScreenCapture


def main():
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    region = None
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        region = (cfg.get("capture") or {}).get("region")

    os.makedirs("logs", exist_ok=True)
    cap = ScreenCapture(region=region, fps=30)
    time.sleep(0.5)
    frame = cap.latest()
    cap.stop()
    if frame is None:
        print("❌ 没抓到帧：检查显卡驱动 / 是否独占全屏 / dxcam 安装")
        return 1
    out = os.path.join("logs", "selftest.png")
    cv2.imwrite(out, frame)
    mean = float(frame.mean())
    print(f"✅ 抓到 {frame.shape[1]}x{frame.shape[0]}，平均亮度 {mean:.1f} → {out}")
    if mean < 5:
        print("⚠️ 画面几乎全黑：游戏大概率还是独占全屏，改成窗口化无边框")
    return 0


if __name__ == "__main__":
    sys.exit(main())
