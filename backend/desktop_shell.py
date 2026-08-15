"""ABcode Windows 桌面壳

用 pywebview（系统 WebView2/EdgeChromium）把 8900 前端包成原生应用窗口，
与 macapp（Swift+WKWebView）体验对齐：打开 exe = 打开 ABcode 应用，而非浏览器标签页。

在 frozen(Windows) 模式下由 main.py 自动调用；源码模式也可独立运行：
    python backend/desktop_shell.py
"""
import os
import sys
import threading
import time
import urllib.request

PORT = int(os.environ.get("PORT", "8900"))
URL = f"http://127.0.0.1:{PORT}/"


def _backend_ready(timeout_sec=2.0) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/providers", timeout=timeout_sec)
        return True
    except Exception:
        return False


def run(app, host: str = "127.0.0.1", port: int = PORT) -> None:
    """在当前进程内启动后端线程，然后打开桌面窗口。"""
    import webview

    # 1. 后端以线程方式跑（uvicorn.run 会阻塞主线程，必须放子线程）
    if not _backend_ready():
        def _serve():
            import uvicorn
            uvicorn.run(app, host=host, port=port)

        threading.Thread(target=_serve, daemon=True).start()

        # 2. 等待后端就绪（最多 30s）
        for _ in range(30):
            if _backend_ready():
                break
            time.sleep(1)

    # 3. 打开应用窗口
    webview.create_window(
        "ABcode",
        URL,
        width=1280,
        height=860,
        min_size=(960, 640),
    )
    webview.start()


if __name__ == "__main__":
    # 独立运行：直接跑 FastAPI 应用（复用 main.app）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import main  # noqa: E402

    run(main.app)