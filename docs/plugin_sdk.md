# Search Cat 插件 SDK（第一版）

## 插件结构

```text
plugins/<plugin-id>/
├── plugin.json
├── main.py
├── config.schema.json
└── assets/
```

插件运行数据保存在 `plugin_data/<plugin-id>/`，不会写入插件安装目录。

## 清单

```json
{
  "id": "com.example.plugin",
  "name": "示例插件",
  "version": "1.0.0",
  "sdk_version": "1",
  "entry": "main.py",
  "description": "插件说明",
  "permissions": [
    "window.bind",
    "screen.capture",
    "mouse.foreground",
    "filesystem.plugin_data"
  ],
  "config_schema": "config.schema.json"
}
```

当前宿主权限包括：

- `window.bind`
- `screen.capture`
- `mouse.foreground` / `mouse.background`
- `keyboard.foreground` / `keyboard.background`
- `filesystem.plugin_data`

权限限制的是宿主 SDK 调用。Python 子进程提供故障隔离，但不是针对不可信 Python 代码的完整安全沙箱。

## 生命周期

```python
def on_load(context):
    pass


def on_start(context):
    pass


def on_stop(context):
    pass


def on_unload(context):
    pass
```

`on_start` 是必需入口，其他函数可选。

## 窗口和截图

```python
window = context.windows.current()
alive = context.windows.is_alive()

frame = context.capture.window(
    mode='auto',             # auto/background/foreground
    area='client',           # window/client
    region=(0, 0, 400, 300),
)
```

后台截图失败时，只有 `auto` 模式会回退到前台截图；显式 `background` 模式会直接报错。

## 找图和取色

```python
match = context.vision.find_image(
    frame,
    resource='images/button.png',
    threshold=0.85,
    grayscale=True,
)

color = context.vision.get_color(frame, 100, 200, order='RGB')
comparison = context.vision.compare_color(color, [44, 28, 49], tolerance=30)
```

资源路径始终相对于插件的 `assets/`，并禁止使用 `../` 离开资源目录。

## 键鼠

```python
context.mouse.click(
    200,
    300,
    button='left',
    mode='background',
    coordinate_space='client',
)

context.keyboard.press('f1', mode='background')
context.keyboard.hotkey('ctrl', 'a', mode='foreground')
```

模拟运行时，键鼠方法返回预计操作，但不会发送真实输入。后台失败不会自动切换为前台。

## 步骤、日志和变量

```python
with context.step('查找按钮'):
    match = context.vision.find_image(frame, 'images/button.png')
    context.debug.watch('match_score', match.score)
    context.log(f'匹配分数：{match.score}')
```

每个 SDK 调用、步骤和异常都会写入本次运行目录的 `events.jsonl` 与 `run.log`。

## 独立存储

```python
state = context.storage.read_json('state.json', default={})
context.storage.write_json('state.json', state)
```

所有路径均被限制在 `plugin_data/<plugin-id>/data/`。

## 紧急停止

全局快捷键 `Ctrl+Shift+F12` 会停止当前自动化功能和插件进程。插件进程先请求正常终止，两秒后仍未退出则强制结束。
