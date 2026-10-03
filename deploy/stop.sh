#!/usr/bin/env bash
# 一键停止 voice agent 服务
cd "$(dirname "$0")"
PID_FILE=server.pid

if [ ! -f "$PID_FILE" ]; then
    echo "服务未运行（无 pid 文件）"
    exit 0
fi
PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    for i in $(seq 1 20); do
        kill -0 "$PID" 2>/dev/null || break
        sleep 0.5
    done
    kill -0 "$PID" 2>/dev/null && kill -9 "$PID"
    echo "已停止：pid $PID"
else
    echo "进程不存在：pid $PID（清理 pid 文件）"
fi
rm -f "$PID_FILE"
