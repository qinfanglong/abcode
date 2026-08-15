#!/bin/bash
# 钉钉 Stream 链路一键验证脚本 (由 QA Agent 生成)
set -e
cd "$(dirname "$0")"

PY=python3
DB=data/abcode.db
LOG=backend/uvicorn_8900.log

echo "===== [1/4] 检查钉钉凭据 ====="
CFG=$($PY -c "
import sqlite3,json
c=sqlite3.connect('$DB')
cfg=json.loads(c.execute(\"SELECT config FROM channels WHERE id='dingtalk'\").fetchone()[0])
ak=(cfg.get('app_key') or '').strip(); ak2=(cfg.get('client_id') or '').strip()
asc=(cfg.get('app_secret') or '').strip(); asc2=(cfg.get('client_secret') or '').strip()
ak=(ak or ak2); asc=(asc or asc2)
print('APP_KEY=%s' % ak)
print('APP_SECRET=%s' % asc)
print('ok=%s' % ('1' if ak and asc else '0'))
")
echo "$CFG"
OK=$(echo "$CFG" | grep '^ok=' | cut -d= -f2)
if [ "$OK" != "1" ]; then
  echo "❌ 凭据为空：请先在 ABcode 频道配置里填入 AppKey / AppSecret 并保存"
  exit 1
fi
echo "✅ 凭据已配置"

echo "===== [2/4] 查找 8900 进程 ====="
PID=$(pgrep -f "uvicorn main:app.*8900" | head -1)
if [ -z "$PID" ]; then
  echo "⚠️  未找到 8900 进程，请手动启动"
  exit 1
fi
echo "PID=$PID"

echo "===== [3/4] 重启 8900（需要权限） ====="
# 尝试温和 kill（可能被安全策略拦截，则提示手动）
kill "$PID" 2>/dev/null && echo "已发送 kill 信号" || echo "❌ 安全策略拦截 kill，需你手动执行: kill $PID"
sleep 2
if pgrep -f "uvicorn main:app.*8900" > /dev/null; then
  echo "⚠️  进程仍在，请手动 kill $PID 后重新启动 8900（cd backend && nohup python3 -m uvicorn main:app --host 0.0.0.0 --port 8900 > uvicorn_8900.log 2>&1 &）"
  exit 1
fi
(cd backend && nohup $PY -m uvicorn main:app --host 0.0.0.0 --port 8900 > uvicorn_8900.log 2>&1 &)
echo "✅ 已重启，等待 3 秒..."
sleep 3

echo "===== [4/4] 验证 Stream 连接 ====="
grep -E "Stream|钉钉" "$LOG" | tail -5
if grep -q "钉钉 Stream 机器人已启动" "$LOG"; then
  echo "🎉 Stream 已连接，去钉钉里 @机器人 发消息吧"
else
  echo "⚠️  未看到 Stream 启动日志，检查上方输出；若提示凭据错误则凭据不正确"
fi