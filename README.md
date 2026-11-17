1、修改了c4设备上下载模型的方式为镜像
2、同步了最新的大小模型列表
3、切换模型后开启op会出modeld_tinygrad未启动的错误，还未解决
echo "===== 1. 当前分支和提交 ====="
cd /data/openpilot
git branch --show-current
git rev-parse HEAD

echo "===== 2. 模型启动错误日志 ====="
journalctl -b --no-pager 2>/dev/null | grep -Ei \
'modeld_tinygrad|modeld|tinygrad|Traceback|AssertionError|EOFError|KeyError|ImportError|RuntimeError|Error' | tail -n 200

