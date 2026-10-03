#!/usr/bin/env bash
# 一键启动 voice agent 服务（默认端口 6789）
cd "$(dirname "$0")"
PID_FILE=server.pid
LOG_FILE=reports/server.log

if [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
    echo "服务已在运行：pid $(cat $PID_FILE)"
    exit 0
fi

source "$HOME/miniforge-host/etc/profile.d/conda.sh"
conda activate py310
mkdir -p reports

nohup python -m voice.web_server --config configs/local.json \
    --host 0.0.0.0 --port "${1:-6789}" > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
sleep 3
if kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
    echo "启动成功：pid $(cat $PID_FILE)，端口 ${1:-6789}，日志 $LOG_FILE"
else
    echo "启动失败，请查看 $LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi
