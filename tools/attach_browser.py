"""连接你已经在跑的 Chrome（网易云游戏网页），测试 CDP 能不能发按键。

前置：Chrome 必须带 --remote-debugging-port=9222 启动，见 README 第 9 节。

用法：
    python tools/attach_browser.py                      # 列出所有页面
    python tools/attach_browser.py --test               # 发一次 A 键测试
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdp", default="http://127.0.0.1:9222")
    ap.add_argument("--keyword", default="")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--key", default="j")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.connect_over_cdp(args.cdp)
        except Exception as e:
            print("❌ 连不上 CDP：", e)
            print("   用这条命令启动 Chrome：")
            print(r'   chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\cdp-profile '
                  r'--disable-backgrounding-occluded-windows --disable-renderer-backgrounding')
            return 1

        pages = []
        for c in browser.contexts:
            pages.extend(c.pages)
        print(f"共 {len(pages)} 个页面：")
        for i, p in enumerate(pages):
            print(f"  [{i}] {p.title()[:40]} | {p.url[:90]}")

        page = pages[-1]
        for p in pages:
            if args.keyword and args.keyword in (p.url or ""):
                page = p
                break
        page.bring_to_front()
        print(f"\n选中：{page.title()} | {page.url[:90]}")

        if args.test:
            print(f"\n3 秒后向该页面发送按键 '{args.key}'，请观察云游戏里角色是否有反应…")
            for i in range(3, 0, -1):
                print(" ", i)
                time.sleep(1)
            page.mouse.click(640, 400)
            time.sleep(0.3)
            page.keyboard.down(args.key)
            time.sleep(0.08)
            page.keyboard.up(args.key)
            print("✅ 已发送。没反应就检查：网页是否已点进游戏画面、键位是否和 config 的 key_map 一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
