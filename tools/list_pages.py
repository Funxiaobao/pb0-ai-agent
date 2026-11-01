"""只列页面验证 CDP+playwright 连接：不动窗口焦点、不发任何输入。"""
import sys

from playwright.sync_api import sync_playwright


def main():
    cdp = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9222"
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp)
        pages = []
        for c in browser.contexts:
            pages.extend(c.pages)
        print("CDP 连接成功, 共 %d 个页面:" % len(pages))
        for i, p in enumerate(pages):
            print("  [%d] %s | %s" % (i, p.title()[:40], p.url[:90]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
