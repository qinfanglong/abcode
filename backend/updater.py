"""ABcode 在线更新 - 自动检查、下载、应用更新"""
import json
import os
import platform
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

VERSION = "0.5.0"
APP_NAME = "ABcode"
DEFAULT_UPDATE_URL = ""

# 更新状态
_update_status = {
    "checking": False,
    "downloading": False,
    "applying": False,
    "last_check": 0,
    "last_result": None,
    "download_progress": 0,
    "download_path": "",
    "update_available": False,
    "latest_version": "",
    "changelog": "",
    "error": None,
}

# 更新历史
_update_history = []

# 自动检查线程
_auto_check_thread = None
_auto_check_running = False


def get_platform():
    sys = platform.system().lower()
    return "mac" if sys == "darwin" else ("win" if sys == "windows" else "linux")


def current_version():
    return VERSION


def get_update_status():
    """获取当前更新状态"""
    return _update_status.copy()


def get_update_history():
    """获取更新历史"""
    return _update_history.copy()


def _add_history(action, result, details=""):
    """添加更新历史记录"""
    _update_history.insert(0, {
        "time": time.time(),
        "action": action,
        "result": result,
        "details": details,
    })
    # 只保留最近50条
    if len(_update_history) > 50:
        _update_history.pop()


def check_update(update_url=None, version=None):
    """检查更新，返回 dict"""
    url = (update_url or "").strip()
    if not url:
        return {
            "ok": True,
            "current": VERSION,
            "has_update": False,
            "msg": "未配置更新源",
        }
    
    _update_status["checking"] = True
    _update_status["error"] = None
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ABcode-Updater"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        
        latest = data.get("version", "")
        plat = get_platform()
        download_url = ""
        md5 = ""
        
        files = data.get("files", {})
        entry = files.get(plat, {})
        if entry:
            download_url = entry.get("url", "")
            md5 = entry.get("md5", "")
        elif data.get("download_url"):
            download_url = data["download_url"]
            md5 = data.get("md5", "")

        def ver_tuple(v):
            try:
                return tuple(int(x) for x in str(v).lstrip("v").split("."))
            except Exception:
                return (0,)

        has_update = bool(latest) and ver_tuple(latest) > ver_tuple(version or VERSION)
        
        _update_status["last_check"] = time.time()
        _update_status["update_available"] = has_update
        _update_status["latest_version"] = latest
        _update_status["changelog"] = data.get("changelog", "")
        
        result = {
            "ok": True,
            "current": version or VERSION,
            "latest": latest,
            "has_update": has_update,
            "download_url": download_url,
            "md5": md5,
            "changelog": data.get("changelog", ""),
            "msg": f"发现新版本 {latest}" if has_update else "已是最新版本",
        }
        
        _update_status["last_result"] = result
        _add_history("check", "success", result["msg"])
        
        return result
    except Exception as e:
        error_msg = f"检查失败: {e}"
        _update_status["error"] = error_msg
        _update_status["last_result"] = {"ok": False, "msg": error_msg}
        _add_history("check", "failed", error_msg)
        return {"ok": False, "current": version or VERSION, "has_update": False, "msg": error_msg}
    finally:
        _update_status["checking"] = False


def download_update(url, dest_dir=None):
    """下载更新包到本地，返回 (ok, path, msg)"""
    dest_dir = dest_dir or str(Path.home() / "Downloads")
    os.makedirs(dest_dir, exist_ok=True)
    fname = url.split("/")[-1].split("?")[0] or "abcode_update.zip"
    dest = os.path.join(dest_dir, fname)
    
    _update_status["downloading"] = True
    _update_status["download_progress"] = 0
    _update_status["error"] = None
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ABcode-Updater"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        _update_status["download_progress"] = int(downloaded * 100 / total)
        
        size = os.path.getsize(dest)
        _update_status["download_path"] = dest
        _update_status["download_progress"] = 100
        
        msg = f"下载完成: {fname} ({size//1024//1024}MB)"
        _add_history("download", "success", msg)
        
        return True, dest, msg
    except Exception as e:
        error_msg = f"下载失败: {e}"
        _update_status["error"] = error_msg
        _add_history("download", "failed", error_msg)
        return False, "", error_msg
    finally:
        _update_status["downloading"] = False


def verify_md5(path, expect_md5):
    """校验文件 MD5"""
    if not expect_md5:
        return True
    import hashlib
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expect_md5.lower()


def apply_update(zip_path, md5=None):
    """应用更新：解压并替换文件，然后重启服务"""
    _update_status["applying"] = True
    _update_status["error"] = None
    
    try:
        # 校验 MD5
        if md5 and not verify_md5(zip_path, md5):
            return False, "MD5 校验失败，文件可能已损坏"
        
        # 备份当前版本
        backup_dir = Path.home() / ".abcode" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_name = f"backup_{VERSION}_{int(time.time())}"
        backup_path = backup_dir / backup_name
        
        # 获取当前应用目录
        app_dir = Path(__file__).parent.parent
        frontend_dir = app_dir / "frontend"
        
        # 备份关键文件
        if frontend_dir.exists():
            shutil.copytree(frontend_dir, backup_path / "frontend", dirs_exist_ok=True)
        
        # 解压更新包
        import zipfile
        temp_dir = Path.home() / ".abcode" / "temp_update"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # 查找解压后的内容
        extracted_items = list(temp_dir.iterdir())
        if len(extracted_items) == 1 and extracted_items[0].is_dir():
            source_dir = extracted_items[0]
        else:
            source_dir = temp_dir
        
        # 复制文件
        for item in source_dir.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(source_dir)
                dest_file = app_dir / rel_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest_file)
        
        # 清理临时文件
        shutil.rmtree(temp_dir, ignore_errors=True)
        
        # 记录更新
        _add_history("apply", "success", f"从 {VERSION} 更新到 {_update_status.get('latest_version', 'unknown')}")
        
        # 重启服务
        _restart_service()
        
        return True, "更新已应用，服务正在重启..."
    except Exception as e:
        error_msg = f"应用更新失败: {e}"
        _update_status["error"] = error_msg
        _add_history("apply", "failed", error_msg)
        return False, error_msg
    finally:
        _update_status["applying"] = False


def rollback_update(backup_name):
    """回滚到备份版本"""
    try:
        backup_dir = Path.home() / ".abcode" / "backups" / backup_name
        if not backup_dir.exists():
            return False, "备份不存在"
        
        app_dir = Path(__file__).parent.parent
        frontend_dir = app_dir / "frontend"
        
        # 恢复前端文件
        backup_frontend = backup_dir / "frontend"
        if backup_frontend.exists():
            if frontend_dir.exists():
                shutil.rmtree(frontend_dir)
            shutil.copytree(backup_frontend, frontend_dir)
        
        _add_history("rollback", "success", f"回滚到 {backup_name}")
        
        # 重启服务
        _restart_service()
        
        return True, "回滚完成，服务正在重启..."
    except Exception as e:
        error_msg = f"回滚失败: {e}"
        _add_history("rollback", "failed", error_msg)
        return False, error_msg


def _restart_service():
    """重启 ABcode 服务"""
    try:
        # 获取当前进程信息
        pid = os.getpid()
        
        # 获取backend目录
        backend_dir = str(Path(__file__).parent)
        app_dir = str(Path(__file__).parent.parent)
        
        # 启动新进程
        python_path = shutil.which("python3") or shutil.which("python")
        if python_path:
            subprocess.Popen(
                [python_path, "main.py"],
                cwd=backend_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        
        # 退出当前进程
        os._exit(0)
    except Exception as e:
        print(f"重启失败: {e}")


def start_auto_check(interval_hours=24):
    """启动自动检查线程"""
    global _auto_check_thread, _auto_check_running
    
    if _auto_check_running:
        return
    
    _auto_check_running = True
    
    def auto_check_loop():
        while _auto_check_running:
            try:
                import db
                settings = db.get_all_settings()
                update_url = settings.get("update_url", "")
                
                if update_url:
                    check_update(update_url)
            except Exception as e:
                print(f"自动检查更新失败: {e}")
            
            # 等待下次检查
            for _ in range(interval_hours * 3600):
                if not _auto_check_running:
                    break
                time.sleep(1)
    
    _auto_check_thread = threading.Thread(target=auto_check_loop, daemon=True)
    _auto_check_thread.start()


def stop_auto_check():
    """停止自动检查"""
    global _auto_check_running
    _auto_check_running = False


def tts_say(text):
    """macOS 语音合成，返回 (ok, audio_path)"""
    import tempfile
    try:
        out = tempfile.mktemp(suffix=".aiff")
        proc = subprocess.run(
            ["say", "-o", out, text],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return False, ""
        mp3 = tempfile.mktemp(suffix=".m4a")
        subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", out, mp3],
                       capture_output=True, timeout=30)
        if os.path.exists(mp3) and os.path.getsize(mp3) > 100:
            return True, mp3
        return True, out
    except Exception:
        return False, ""
