"""
Android 入口 —— Kivy 启动器 + 内嵌 WebView
启动 FastAPI 服务器后显示 WebView 界面
"""
import os
import sys
import threading
import webbrowser
import urllib.request
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 加载 .env
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k not in os.environ:
                    os.environ[k] = v

SERVER_PORT = int(os.environ.get("KAI_AGENT_PORT", 8765))


def start_server():
    import uvicorn
    from web_app import app
    uvicorn.run(app, host="127.0.0.1", port=SERVER_PORT, log_level="warning")


class AgentApp:
    def __init__(self):
        self.server_ready = False

    def _wait_for_server(self):
        url = f"http://127.0.0.1:{SERVER_PORT}"
        for _ in range(120):
            try:
                urllib.request.urlopen(url, timeout=1)
                self.server_ready = True
                return
            except Exception:
                time.sleep(0.5)

    def _run(self):
        threading.Thread(target=start_server, daemon=True).start()
        self._wait_for_server()

        from kivy.app import App
        from kivy.lang import Builder
        from kivy.clock import Clock

        KV = """
RelativeLayout:
    Label:
        text: "KAI Agent 启动中..."
        font_size: 24
        center: self.parent.center
"""

        class KivyApp(App):
            def build(self):
                return Builder.load_string(KV)

            def on_start(self):
                Clock.schedule_once(lambda dt: self._show_webview(), 0.1)

            def _show_webview(self):
                from jnius import autoclass
                from android.runnable import run_on_ui_thread

                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                WebView = autoclass("android.webkit.WebView")
                WebViewClient = autoclass("android.webkit.WebViewClient")
                LayoutParams = autoclass("android.view.ViewGroup$LayoutParams")

                @run_on_ui_thread
                def show():
                    activity = PythonActivity.mActivity
                    wv = WebView(activity)
                    wv.getSettings().setJavaScriptEnabled(True)
                    wv.getSettings().setDomStorageEnabled(True)
                    wv.setWebViewClient(WebViewClient())
                    wv.loadUrl(f"http://127.0.0.1:{SERVER_PORT}")
                    activity.setContentView(wv, LayoutParams(-1, -1))

                show()

        KivyApp().run()


if __name__ == "__main__":
    try:
        AgentApp()._run()
    except ImportError:
        print("=" * 50)
        print("  KAI Agent · Server Mode")
        print("=" * 50)
        print(f"\n  Starting server on http://127.0.0.1:{SERVER_PORT}")
        threading.Thread(target=start_server, daemon=True).start()
        time.sleep(1)
        webbrowser.open(f"http://127.0.0.1:{SERVER_PORT}")
        print("  Press Ctrl+C to stop\n")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n  Server stopped.")
