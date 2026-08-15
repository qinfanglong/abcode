"""本地语音识别（faster-whisper 离线 CPU 转写，不依赖云端）

- 模型首次使用自动下载（走 HF 官方；国内网络自动兜底 hf-mirror）
- 默认 base（约 74MB，CPU 转写 <1s）；可用环境变量 ABCODE_ASR_MODEL 换 small/large-v3 等
- faster-whisper 未安装时优雅降级：/api/asr 返回 503 提示
"""
import io
import logging
import os
import threading

logger = logging.getLogger("abcode.asr")

MODEL_SIZE = os.environ.get("ABCODE_ASR_MODEL", "base")
_inited = False
_model = None
_load_lock = threading.Lock()


def _ensure_model():
    """懒加载 faster-whisper 模型；未安装/加载失败返回 None（线程安全）"""
    global _model, _inited
    if _inited:
        return _model
    with _load_lock:
        if _inited:
            return _model
        _inited = True
        try:
            from faster_whisper import WhisperModel
        except Exception as e:
            logger.warning("[asr] faster-whisper 未安装，本地语音识别不可用: %s", e)
            return None
        # 国内网络模型下载镜像兜底（仅首次需下载模型时生效）
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        try:
            logger.info("[asr] 加载本地模型 %s ...", MODEL_SIZE)
            _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
            logger.info("[asr] 本地模型加载完成: %s", MODEL_SIZE)
        except Exception as e:
            logger.error("[asr] 本地模型加载失败: %s", e)
            _model = None
        return _model


def transcribe(data: bytes) -> str:
    """转写音频字节（webm/wav/m4a/aiff 均可，PyAV 自动解码），失败返回空串"""
    model = _ensure_model()
    if model is None:
        return ""
    try:
        segments, _info = model.transcribe(
            io.BytesIO(data),
            language="zh",
            vad_filter=True,
            initial_prompt="以下是简体中文的普通话。",
        )
        return "".join(s.text for s in segments).strip()
    except Exception as e:
        logger.error("[asr] 转写失败: %s", e)
        return ""