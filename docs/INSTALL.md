# 安装与运行指南

ABcode 后端是跨平台 Python（FastAPI），前端是静态页面，因此可以在 **macOS / Windows / Linux** 上以源码方式运行；另外提供 **macOS 原生 App**。

---

## 🍎 macOS

### 方式一：原生 App（推荐）

1. 从 [Releases](https://github.com/<your-name>/abcode/releases) 下载 `ABcode-mac-<version>.zip`
2. 解压，把 `ABcode.app` 拖入「应用程序」
3. 首次运行：右键 → 打开（或系统设置 → 隐私与安全性 → 仍要打开），绕过 Gatekeeper
4. 启动后自动在 `127.0.0.1:8900` 启动后端并加载界面
   - 数据目录：`~/Library/Application Support/ABcode/`
   - 日志：`~/Library/Application Support/ABcode/backend.log`

> 要求 macOS 12+，已安装 Python 3.9+（Xcode Command Line Tools 自带）。App 内嵌全部 Python 依赖，无需手动装包。

### 方式二：源码运行

```bash
brew install python@3.11        # 或使用 Xcode 自带 python3
git clone https://github.com/<your-name>/abcode.git
cd abcode
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
./start.sh
# 浏览器自动打开 http://127.0.0.1:8900
```

> 若需要本地 Ollama 或原生模型，请另行安装相应运行时。

---

## 🪟 Windows

### 前置要求

- Python 3.9+（[python.org](https://www.python.org/downloads/) 安装时勾选 **Add Python to PATH**）
- Git（可选，用于克隆）

### 运行

```bat
git clone https://github.com/<your-name>/abcode.git
cd abcode
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
start.bat
:: 自动打开浏览器 http://127.0.0.1:8900
```

> `start.bat` 会优先使用 `.venv\Scripts\python.exe`，找不到则回退到系统 `python`。
> 若 8900 被占用，可指定端口：`start.bat 9000`。

### 自定义端口（手动）

```bat
python -m uvicorn main:app --host 0.0.0.0 --port 9000 --app-dir backend
```

---

## 🐧 Linux

支持 Debian/Ubuntu、CentOS/RHEL、Arch 等任意发行版。

### 安装依赖

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git
```

### 运行

```bash
git clone https://github.com/<your-name>/abcode.git
cd abcode
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
./start.sh
# 浏览器访问 http://127.0.0.1:8900
```

### 以 systemd 常驻（可选）

```ini
# /etc/systemd/system/abcode.service
[Unit]
Description=ABcode AI Agent
After=network.target

[Service]
WorkingDirectory=/opt/abcode
ExecStart=/opt/abcode/.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8900 --app-dir backend
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now abcode
```

---

## 💾 数据与备份

| 路径 | 说明 |
|------|------|
| `data/abcode.db` | 会话、供应商、偏好、团队等全部数据（SQLite） |
| `data/kb/` | 知识库分块索引 |
| `data/uploads/` | 附件 |
| `data/connectors/` | 连接器配置 |

这些目录**不入库**（见 `.gitignore`），直接复制即可备份。删除后重新运行会自动重建。

---

## 🐳 Docker（路线图 / 手动）

```bash
# 临时手动方式（后续提供官方镜像）
docker build -t abcode .
docker run -p 8900:8900 -v $(pwd)/data:/app/data abcode
```

---

## ⚠️ 常见问题

| 问题 | 解决 |
|------|------|
| 打开是空白页 | 确认后端已启动、端口未被占用；`FRONTEND_DIR` 需指向 `frontend/` 目录 |
| 端口冲突 | 换端口：`PORT=9000 ./start.sh` 或 `start.bat 9000` |
| 首次运行报缺依赖 | `pip install -r backend/requirements.txt` |
| Mac App 提示已损坏 | 右键 → 打开，或 `xattr -cr /Applications/ABcode.app` |