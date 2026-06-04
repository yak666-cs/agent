[app]

title = KAI Agent
package.name = kaiagent
package.domain = org.kai.agent
source.dir = .
source.main = mobile/main.py
version = 1.0.0

requirements = python3,kivy,fastapi,uvicorn,httpx,pyjnius

orientation = portrait
osx.python_version = 3.11
presplash.color = #1a1a2e
icon = static/icon.png

# Android
android.permissions = INTERNET
android.api = 33
android.minapi = 24
android.gradle_dependencies = 'androidx.webkit:webkit:1.6.0'
android.enable_androidx = True
android.accept_sdk_license = True
android.ndk = 23b
android.sdk = 33

# 包含 web 前端文件
source.include_exts = py,png,jpg,kv,atlas,html,js,css,txt
source.include_patterns = *.py,static/*,mobile/*.py,agent/*.py,tools/*.py,tools/builtin/*.py,skills/*.py,skills/builtin/*.py,harness/*.py,.env

# 排除
source.exclude_patterns = tests/*,__pycache__/*,*.pyc

[buildozer]
log_level = 2
warn_on_root = 1
