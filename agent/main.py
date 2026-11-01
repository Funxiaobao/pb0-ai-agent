"""主循环：抓屏 → 决策 → 宏队列 → 日志/HUD。

启动：
    python -m agent.main config.yaml
急停：F12（全局，不需要窗口焦点）
"""
import json
import os
import sys
import time
from datetime import datetime

import cv2
import yaml
from pynput import keyboard

from .capture import ScreenCapture
from .controller import MacroPlayer
from .policy import Policy


class Stop:
    def __init__(self):
        self.flag = False
        self.key = keyboard.Key.f12

    def listen(self):
        def on_press(k):
            if k == self.key:
                self.flag = True
                print("\n[stop] 收到急停")
        self.listener = keyboard.Listener(on_press=on_press)
        self.listener.daemon = True
        self.listener.start()

    def __bool__(self):
        return self.flag


def write_state(path, thought, macro, hp_note=""):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"thought": thought, "macro": macro, "note": hp_note,
                   "ts": datetime.now().strftime("%H:%M:%S")}, f, ensure_ascii=False)
    os.replace(tmp, path)


def main():
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    log_dir = cfg.get("log", {}).get("dir", "logs")
    os.makedirs(log_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"episode_{stamp}.jsonl")
    state_path = os.path.join("overlay", "state.json")
    os.makedirs("overlay", exist_ok=True)

    cap_cfg = cfg.get("capture", {})
    pol_cfg = dict(cfg.get("policy", {}))
    pol_cfg.setdefault("max_width", cap_cfg.get("max_width", 960))

    print("[init] 抓屏…")
    in_cfg = cfg.get("input", {}) or {}
    region = cap_cfg.get("region")
    if region == "auto":
        region = None
        try:
            from .browser_input import probe_video_region
            r = probe_video_region(in_cfg.get("cdp_url", "http://127.0.0.1:9222"),
                                   in_cfg.get("page_keyword", ""))
            if r:
                region = r
                print("[init] 自动探测到视频区域:", r)
        except Exception as e:
            print("[init] 区域探测失败, 回退全屏:", e)
    cap = ScreenCapture(region=region, fps=int(cap_cfg.get("fps", 30)))
    # 输入后端：本地游戏用 gamepad；网页版云游戏用 cdp（键盘事件注入浏览器）
    backend = in_cfg.get("backend", "gamepad")
    if backend == "gamepad":
        print("[init] 虚拟手柄…")
        player = MacroPlayer(cfg.get("controller", {}).get("button_map", {}),
                             cfg.get("controller", {}))
    else:
        print(f"[init] 浏览器输入（CDP {in_cfg.get('cdp_url')}）…")
        try:
            from .browser_input import KeyMacroPlayer
        except ImportError:
            raise SystemExit("[err] 当前是本地手柄版，没有 CDP 模块；"
                             "云游戏请用 main 分支，或把 input.backend 设成 gamepad")
        player = KeyMacroPlayer(in_cfg)
    player.start()
    policy = Policy(pol_cfg)

    stop = Stop()
    stop.listen()
    interval = float(cap_cfg.get("model_every", 1.0))
    max_min = float(cfg.get("safety", {}).get("max_session_minutes", 120))
    stuck_secs = float(cfg.get("safety", {}).get("stuck_window_seconds", 25))

    t_start = time.time()
    last_call = 0.0
    last_macro = ""
    repeat = 0
    last_gray = None
    last_change = time.time()
    n = 0

    # 给 3 秒切回游戏窗口
    print("[init] 3 秒后开始，请让游戏窗口在前台")
    for i in range(3, 0, -1):
        print("  ", i)
        time.sleep(1)

    try:
        while not stop:
            if time.time() - t_start > max_min * 60:
                print("[stop] 超时")
                break
            frame = cap.latest()
            if frame is None:
                time.sleep(0.05)
                continue

            # 画面变化检测：长时间同画面 = 卡住
            small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64, 36))
            if last_gray is not None and float(cv2.absdiff(small, last_gray).mean()) > 6.0:
                last_change = time.time()
            last_gray = small
            if time.time() - last_change > stuck_secs:
                print("[recover] 画面长时间没变化，播 ui_recover")
                player.submit("ui_recover")
                last_change = time.time()

            now = time.time()
            if now - last_call < interval:
                time.sleep(0.02)
                continue
            last_call = now

            try:
                d = policy.decide(frame)
            except Exception as e:
                print("[policy] 失败:", e)
                player.submit("guard:1.0")
                time.sleep(0.5)
                continue

            # 连续重复同一宏 → 强制换个动作，防发呆
            if d["macro"] == last_macro:
                repeat += 1
                if repeat >= 3:
                    d["macro"] = "move:forward:0.8"
                    d["thought"] += "（重复太久，强制前进）"
                    repeat = 0
            else:
                repeat = 0
            last_macro = d["macro"]

            player.submit(d["macro"])
            n += 1
            print(f"[{n:04d}] {d['latency_ms']:>5}ms  {d['thought']}  ->  {d['macro']}")

            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": round(now - t_start, 2),
                    "frame": n,
                    "thought": d["thought"],
                    "macro": d["macro"],
                    "latency_ms": d["latency_ms"],
                    "player_current": player.current,
                }, ensure_ascii=False) + "\n")
            write_state(state_path, d["thought"], d["macro"])
            if cfg.get("log", {}).get("save_frames"):
                cv2.imwrite(os.path.join(log_dir, f"f_{n:04d}.jpg"), frame)
    except KeyboardInterrupt:
        pass
    finally:
        player.stop()
        cap.stop()
        write_state(state_path, "已停止", "-")
        print(f"[done] 共 {n} 次决策，日志 {log_path}")


if __name__ == "__main__":
    main()
