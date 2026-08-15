#!/bin/bash
# ABcode backend 重启脚本（仅目标：8900 端口的 uvicorn 后端进程）
cd /Users/runkj/.qwenpaw/workspaces/default/abcode/backend || exit 1

OLD_PID=$(lsof -tiTCP:8900 -sTCP:LISTEN 2>/dev/null | head -1)
if [ -n "$OLD_PID" ]; then
  kill "$OLD_PID" 2>/dev/null
  sleep 1.5
fi

nohup /Applications/Xcode.app/Contents/Developer/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python \
  -m uvicorn main:app --host 0.0.0.0 --port 8900 > /tmp/abcode_server.log 2>&1 &

sleep 3
echo -n "重启完成，HTTP状态: "
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8900/