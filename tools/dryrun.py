"""只读链路演练：抓屏 -> (mock)决策 -> 宏解析 -> 日志，不注入任何输入。"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.capture import ScreenCapture
from agent.policy import Policy
from agent.actions import parse_macro


class StubPlayer:
    def __init__(self):
        self.current = ""

    def submit(self, m):
        self.current = m


def main():
    cap = ScreenCapture(region=None, fps=30)
    pol = Policy({"base_url": "mock", "model": "x", "api_key": "x",
                  "timeout": 8, "max_tokens": 220, "temperature": 0.2,
                  "history_turns": 4, "max_width": 960})
    player = StubPlayer()
    os.makedirs("logs", exist_ok=True)
    print("链路演练开始（8 轮, 每轮 1 秒, 不注入输入）...")
    for i in range(8):
        frame = cap.latest()
        assert frame is not None, "抓屏无帧"
        d = pol.decide(frame)
        steps = parse_macro(d["macro"])
        assert steps, "宏解析为空"
        player.submit(d["macro"])
        print("[%02d] %s -> %s (steps=%d, frame=%dx%d)" % (
            i + 1, d["thought"], d["macro"], len(steps),
            frame.shape[1], frame.shape[0]))
        with open("logs/dryrun.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"i": i, "macro": d["macro"]}, ensure_ascii=False) + "\n")
        time.sleep(1.0)
    cap.stop()
    print("链路演练通过（抓屏/决策/解析/日志均正常）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
