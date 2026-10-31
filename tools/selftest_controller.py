"""验证虚拟手柄：默认按一下"跳跃"，游戏里角色应该跳。

用法：
    python tools/selftest_controller.py
    python tools/selftest_controller.py --action light
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

from agent.controller import MacroPlayer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--action", default="jump")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    bmap = {}
    if os.path.exists(args.config):
        with open(args.config, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        bmap = (cfg.get("controller") or {}).get("button_map") or {}
    player = MacroPlayer(bmap).start()

    print(f"3 秒后执行 {args.action}，请让游戏窗口在前台…")
    for i in range(3, 0, -1):
        print(" ", i)
        time.sleep(1)
    player.submit(args.action)
    time.sleep(1.5)
    player.stop()
    print("✅ 已执行。若游戏没反应：ViGEmBus 是否装了并重启？游戏是否切到了键鼠模式？")
    return 0


if __name__ == "__main__":
    sys.exit(main())
