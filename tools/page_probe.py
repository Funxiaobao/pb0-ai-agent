"""只读探测云游戏页面状态：焦点/指针锁定/视频流。不注入任何输入。"""
import json
import sys

from playwright.sync_api import sync_playwright


def main():
    cdp = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9222"
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp)
        pages = []
        for c in browser.contexts:
            pages.extend(c.pages)
        page = None
        for p in pages:
            if "cg.163.com" in (p.url or ""):
                page = p
                break
        if page is None:
            print("没找到 cg.163.com 页面")
            return 1
        info = page.evaluate("""(() => {
            const v = document.querySelector('video');
            const r = v ? v.getBoundingClientRect() : null;
            const dpr = window.devicePixelRatio || 1;
            return {
                title: document.title,
                hasFocus: document.hasFocus(),
                pointerLocked: document.pointerLockElement !== null,
                dpr: dpr,
                video: v ? {
                    readyState: v.readyState,
                    videoWidth: v.videoWidth,
                    videoHeight: v.videoHeight,
                    paused: v.paused,
                    currentTime: v.currentTime.toFixed(1),
                    rectCss: r ? [r.left, r.top, r.right, r.bottom] : null,
                    rectPhysical: r ? [Math.round(r.left * dpr), Math.round(r.top * dpr),
                                       Math.round(r.right * dpr), Math.round(r.bottom * dpr)] : null
                } : null
            };
        })()""")
        print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
