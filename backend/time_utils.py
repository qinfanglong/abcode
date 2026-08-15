"""ABcode 公共工具函数"""
from datetime import datetime
from zoneinfo import ZoneInfo


def get_current_time_str(timezone: str = "Asia/Shanghai") -> str:
    """返回当前时间的可读字符串，供系统提示注入"""
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = None
    now = datetime.now(tz) if tz else datetime.now()
    # 中文友好格式：2026年8月7日 星期四 14:30
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    wd = weekdays[now.weekday()]
    return f"{now.year}年{now.month}月{now.day}日 {wd} {now.strftime('%H:%M')}"


TIME_PROMPT_TPL = "\n\n[系统信息] 当前时间：{time}，时区：Asia/Shanghai。回答中涉及时间时请以此为准。"
