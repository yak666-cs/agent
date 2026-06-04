#!/bin/bash
# APK Build Script - run inside Ubuntu WSL
set -e
cd "$(dirname "$0")"

echo "=== 1. 安装系统依赖 ==="
sudo apt update -qq
sudo apt install -y -qq \
    python3 python3-pip python3-venv \
    git zip unzip openjdk-17-jdk \
    autoconf libtool pkg-config zlib1g-dev \
    libncurses5-dev libncursesw5-dev libtinfo5 \
    cmake libffi-dev libssl-dev 2>&1 | tail -3

echo "=== 2. 安装 Buildozer ==="
pip3 install --upgrade buildozer cython 2>&1 | tail -3

echo "=== 3. 配置 PyPI 镜像（国内加速）==="
pip3 config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple 2>/dev/null

echo "=== 4. 创建 .env（API Key）==="
echo "DEEPSEEK_API_KEY=sk-55997f8d9e7c4b3a2f1d0e8c7a6b5c4d3e2f1a0b" > .env

echo "=== 5. 开始编译 APK（首次约30-60分钟）==="
buildozer android debug --verbose 2>&1

echo "=== 完成 ==="
ls -la bin/
