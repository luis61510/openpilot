
1、同步了最新的大小模型列表
2、修复模型缓存清理
3、修复默认大模型 ref
4、移植了 新版 load_model()  
5、增加   Chestnut eGPU 温度与性能监控（显示核心温度、显存温度、占用率、风扇转速）
6、增加   lead vehicle info TTC显示信息，仅显示前车距离参数。
7、增加   dragpilot中的opview投屏功能。
8、将 红绿灯ui，修改为1个红绿灯显示状态。

11月25号
基于大模型性能的修改：
1、AMD GPU 等待超时	改为 AMDDevice.wait_timeout_ms = 3000
2、实时调度时机	将 config_realtime_process(7, 54) 移到模型加载和预热完成之后
3、大模型缓存预热	扩展 Offroad 预热进程，支持检查并预热 Chestnut AMD 模型缓存

4、修复问题1:split / multi-policy 大模型输出的 NaN、Inf 检查
5、修复问题2:modelV2 旧数据继续被使用
6、修复问题3:大模型运行时故障后无法自动恢复，已增加自动恢复机制
7、修复问题4:预热子进程超时保护
8、修复问题5:大模型加载线程生命周期
9、修复问题6:模型选择代码默认使用 bundle 的第一个模型

11月26号（主要解决大模型切换后，无法启动modeld_tinygrad无法启动的问题）
models/helpers.py	同时识别 supercombo 和 chunked，让新目录中的大小模型都能找到驾驶模型
modeld_v2/modeld.py	选中模型没有可用 artifact 时，尝试加载本地捆绑模型
modeld_v2/modeld.py	小模型加载增加异常保护，避免大模型失败后小模型异常直接导致进程退出
modeld_v2/modeld.py	ChestnutActive 改为根据实际加载模型的 model.chestnut 判断
test_fallback.py	增加 chunked 类型识别和实际 artifact 路径测试



