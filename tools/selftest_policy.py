"""验证视觉模型：拿一帧真实画面问一次，打印 JSON 决策。

用法：
    python tools/selftest_policy.py            # 抓实时画面
    python tools/selftest_policy.py xx.jpg     # 用指定图片
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import yaml

from agent.capture import ScreenCapture
from agent.policy import Policy


def main():
    args = sys.argv[1:]
    cfg_path = "config.yaml"
    img_path = None
    for a in args:
        if a.endswith((".jpg", ".png")):
            img_path = a
        else:
            cfg_path = a
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    pol_cfg = dict(cfg["policy"])
    pol_cfg.setdefault("max_width", (cfg.get("capture") or {}).get("max_width", 960))
    policy = Policy(pol_cfg)

    if img_path:
        frame = cv2.imread(img_path)
        assert frame is not None, f"读不到图：{img_path}"
    else:
        cap = ScreenCapture(region=(cfg.get("capture") or {}).get("region"), fps=30)
        time.sleep(0.5)
        frame = cap.latest()
        cap.stop()
        assert frame is not None, "抓屏失败"

    print(f"模型 {pol_cfg['model']} @ {pol_cfg['base_url']}")
    d = policy.decide(frame)
    print(json.dumps(d, ensure_ascii=False, indent=2))
    if d["latency_ms"] > 3000:
        print("⚠️ 单次超过 3 秒：动作游戏会明显卡顿，考虑换小模型/降分辨率/用量化")
    return 0


if __name__ == "__main__":
    sys.exit(main())
