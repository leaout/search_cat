# QQ三国官爵任务插件

## 使用前提

1. 角色已经取得官爵，并且当天尚未完成官爵任务。
2. 角色站在本国主城的奋威中郎将附近，按 `G` 可以与其对话。
3. 游戏右侧任务追踪栏已经显示，并已校准 OCR 区域。
4. 首次运行必须勾选“模拟运行”。

## 校准

配置中的坐标全部是游戏客户区坐标：

- `task_region`：右侧任务栏客户区区域 `[x, y, width, height]`。
- `npc_routes`：NPC 名称到 `[地图ID, 小地图X, 小地图Y]` 的映射。
- `friend_tab_point`、`add_friend_point`、`friend_input_point`、`generated_link_point`：代码寻路界面坐标。
- `accept_point`：奋威中郎将对话中的领取按钮。
- `continue_point`：中间 NPC 对话的继续或完成按钮。
- `complete_point`：最后领取俸禄的按钮。

在模拟模式观察日志，确认所有预计点击坐标正确后，将 `calibrated` 设置为 `true`。模拟模式不会发送真实键鼠输入。

插件会持续 OCR 任务栏。只有任务文字变化才确认进入下一步；路由库没有目标 NPC 时，会点击 OCR 识别到的任务文字使用游戏原生寻路。

## 可选模板

在脚本平台选择本插件后，通过“识别模板”一栏分别导入以下按钮截图，平台会自动保存到 `assets/images/`。全部显示已配置后，再启用 `use_templates`：

```text
accept.png
continue.png
complete.png
```

模板模式默认在识别失败时停止。只有明确启用 `allow_coordinate_fallback` 后，才会回退到配置坐标。第一版不会自动判断角色是否被地图、战斗或其他弹窗阻挡。
## 游戏数据导入

在“自动化脚本平台”选中本插件后，点击“导入游戏数据”。程序会自动定位 QQ 三国安装目录，
只读解析 `data/objects.pkg` 内的 `res/Txt/MapData.txt`，使用当前客户端地图 ID 与插件坐标源合并，
并把结果写入插件配置的 `npc_routes`。该过程不会解包全部资源，也不会修改游戏文件。

首批内置坐标覆盖蜀国官爵任务常见 NPC。未匹配地图和重名 NPC 不会静默选取错误路线，导入完成后会显示统计。
坐标源位于 `assets/data/npc_locations.json`，每项格式为：

```json
{"name": "奋威中郎将", "map": "成都.子城", "x": 11, "y": 7}
```

首批坐标依据 [巴哈姆特 QQ 三国蜀国 NPC 资料](https://wiki2.gamer.com.tw/wiki.php?n=36531%3A%E8%9C%80%E5%9C%8BNPC)
整理；地图 ID 始终以本机当前游戏包为准。
