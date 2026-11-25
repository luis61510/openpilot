
1、同步了最新的大小模型列表
2、修复模型缓存清理
3、修复默认大模型 ref
4、移植了 新版 load_model()  
5、增加   Chestnut eGPU 温度与性能监控（显示核心温度、显存温度、占用率、风扇转速）
6、增加   lead vehicle info TTC显示信息，仅显示前车距离参数。
7、增加   dragpilot中的opview投屏功能。
8、将 红绿灯ui，修改为1个红绿灯显示状态。

11月25号
9、AMD GPU 等待超时	改为 AMDDevice.wait_timeout_ms = 3000
10、实时调度时机	将 config_realtime_process(7, 54) 移到模型加载和预热完成之后
11、大模型缓存预热	扩展 Offroad 预热进程，支持检查并预热 Chestnut AMD 模型缓存
