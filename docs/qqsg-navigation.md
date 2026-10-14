# QQ三国插件位置读取和寻路接入

本功能已集成到 Search Cat 的脚本平台，无需单独运行 REA。
REA 用于分析客户端数据；运行时使用项目现有 OCR、绑定窗口和前台输入调度器。

## 在界面中使用

1. 进入脚本平台，点击“刷新”。
2. 选择“QQ三国位置读取与原生寻路”。
3. 自动检测游戏窗口，确认四个窗口均已绑定。
4. 在“配置”中确认 `game_directory`，默认 `navigate: false`。
5. 模拟运行只检查配置和地图包；取消模拟运行后，“启动全部”持续读取四个窗口。
6. 查看每个窗口的日志、调试变量“当前位置”；“停止全部”结束读取。

设置目标和开启寻路参见 [位置插件说明](../plugins/com.searchcat.qqsg.position/README.md)。
启动全部采用同一份目标配置，全部绑定角色会尝试前往同一目标。
读数由 OCR 获取，会激活窗口；读取失败不是到达，也不沿用旧坐标。

## 现有插件如何复用

采矿和官爵任务的原生寻路使用 `plugin_platform.qqsg_code_navigation.navigate_and_wait`；
行脚地形插件也通过 SDK 的 `read_navigation_state` 读取小地图。
它们最终进入 `automation.qqsg_code_navigation.read_navigation_state`，
因此共享展开/折叠小地图读取修复、临时截图释放和冲突读数拒绝。
行脚地形移动仍使用它原有的方向键、跳跃和攀爬策略。

```python
from plugin_platform.qqsg_code_navigation import navigate_and_wait

# 返回 {"map_name": "秃龙洞口", "position": [6, 4]} 或 None。
state = context.windows.read_navigation_state(["秃龙洞口"])
if state is not None:
    context.debug.watch("当前位置", state)

# 示例：地图ID应从当前客户端 objects.pkg 的 MapData.txt 查得。
# 小地图坐标 (6,4) 转为原生接口坐标 (600,400)。
navigate_and_wait(context, map_id, 600, 400, "秃龙洞口")
```

读取需要声明 `window.bind` 和 `screen.capture`；原生寻路还需
`mouse.foreground`、`keyboard.foreground` 以及保存寻路状态的 `filesystem.plugin_data`。
省略地图列表时保留旧的采矿地图默认值；其他任务应显式传入地图名。
开启 diagnostics 时，失败可能返回仅含 diagnostic 的字典，应检查 map_name 和 position。

## 打包与验证

`gui.spec` 已包含插件目录和共用地图/寻路模块。
当前修改是源码集成，已有 dist 中的 exe 需要重新构建才能包含代码修复。
可运行离线回归测试：

```powershell
python -m unittest tests.test_code_navigation tests.test_position_plugin tests.test_official_task_navigation tests.test_plugin_platform -q
```

运行 GUI 和重新构建仍需要带有项目依赖的 Python 环境。
离线测试验证协议、插件配置、读取失败和多窗口数据隔离；不表示已在游戏中实测移动成功。
