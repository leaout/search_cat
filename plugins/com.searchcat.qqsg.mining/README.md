# QQ 三国多窗口挖矿插件

插件默认流程是：切换到 14 线 → 按配置动作前往矿区 → 进入矿区后沿四个巡逻段移动 → 在每个巡逻点按 G → 等待整点刷新后继续下一轮。脚本平台的“启动全部”会为每个已绑定的游戏窗口启动一个独立插件进程，因此每个窗口有自己的日志和停止状态；前台按键由平台逐个串行执行，避免多个窗口抢焦点。

## 使用方式

1. 把需要挖矿的 QQ 三国窗口逐个绑定到脚本平台。
2. 将 `target_line` 保持为 `14`，并保持 `switch_line_enabled: true`。
3. 配置 `travel_actions`，例如 `[{"direction":"right","seconds":8,"jump":false}]`。每个动作执行一次，支持 `left/right/up/down`、`seconds` 和 `jump`。
4. 配置 `patrol_route`，例如四段移动：`[{"direction":"right","seconds":3,"g_count":1},{"direction":"left","seconds":6,"g_count":1}, ...]`。每段移动结束后插件会按 G。
5. 先勾选模拟运行测试换线、移动和按键顺序；确认无误后取消模拟运行并点击“启动全部”。

如果角色已经在矿区，可以把 `skip_travel` 设为 `true`。如果只想调试采集动作，可以只保留 `patrol_route`，先不执行跨地图路线。

`refresh_wait_enabled: true` 时，每轮巡逻完成后会等到下一个整点；如果不需要等待，可关闭它。`patrol_loops: 0` 表示持续巡逻，直到用户停止脚本。

插件仍保留了可选的 `template` 模式：将 `mining_mode` 改为 `template`，导入矿点模板后才会启用截图找矿。默认的 `patrol_g` 模式按照你描述的游戏机制直接走位并按 G，不依赖矿点模板。

## 当前边界

目前路线采用动作配置而不是猜测固定坐标：不同角色起点和线路地图可能不同，直接写死路线容易把角色带到错误地图。后续可以根据你录制的一次成功路线，把 `travel_actions` 和 `patrol_route` 保存成默认配置。

公开攻略多以“右键矿点”描述旧版本操作；你当前客户端是进入矿区后按 G 触发采集，所以默认按 G，模板右键模式仅保留作兼容调试。

参考：

- [百度知道：QQ 三国挖矿基础操作](https://zhidao.baidu.com/question/1249584298830407459.html)
- [QQ 三国搬砖攻略（矿区与矿镐说明）](https://www.guowaiwangzhuan.com/1592.html)
- [17173 QQ 三国地图资料](https://qqsg.17173.com/zhinan/map/weimap21.shtml)
