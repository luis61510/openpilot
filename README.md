10月15号onemiess/dev-sp 为基础的主要分支 ，修改了以下功能：
1、增加   Chestnut eGPU 温度与性能监控（显示 普通核心平均温度75、显存温度87、占用率70、风扇转速1200）
2、增加   lead vehicle info TTC显示信息，仅显示前车距离参数，p档时不显示。
3、增加   dragpilot中的opview投屏功能。


------------------------------------------------------------------------------------------------------------------------
同步官方最新的大小模型列表，修改了json地址
同步官方模型下载管理器，并优先使用 hf-mirror.com 镜像下载模型

模型选择 UI	Settings 新增 Models 页面，分别选择 Small Model 和 Big Model
模型清单	接入 81 个 Qualcomm 小模型、25 个 Chestnut 大模型
默认模型	支持恢复 Default，不要求模型清单必须先下载成功
Params	注册 ActiveBundle、ActiveBundleChestnut、DownloadRef、ModelsCache、RunnerTypeCache 等参数
下载状态	UI 订阅 modelManagerSP，显示下载进度和状态
下载控制	支持刷新模型清单、取消下载
消息定义	将 modelManagerSP 注册到 Cereal service 和 Event union
modeld 动态加载	根据小模型/大模型各自的 ActiveBundle，定位对应 .pkl 文件
默认回退	未选择自定义模型时，继续使用原有编译模型
Runner 校验	当前清单的 106 个模型全部是 Tinygrad Runner；加载前增加 Runner 类型检查


1. 移植官方 Stock 模型运行入口及其缺失依赖。
2. 将现有 Chestnut / AMD eGPU 模型加载实现保留为独立 Tinygrad 运行入口。
3. 移植官方 Runner 判断和 `process_config.py` 动态分流。
4. 检查默认小模型、默认大模型、非默认小模型、非默认大模型四条加载路径。
5. 验证切换、取消、缓存、异常恢复和进程重启行为。
