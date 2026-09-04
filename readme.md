[English](readme_en.md) | 简体中文

# 搜索猫（Search Cat）

搜索猫是一款仅支持 Windows 的桌面自动化工具。当前 GUI 集成 OCR 识图答题、鼠标/键盘连点、窗口循环按键、坐标采集和 YOLO 目标检测，并通过 Home 键启动或停止当前选中的功能。

> 本文档描述当前仓库中的实际实现。程序会模拟鼠标和键盘操作，使用前请先在无风险窗口中测试坐标、按键和识别结果。

## 当前功能

### OCR 识图搜索

- 使用 PaddleOCR 2.7（中文模型）识别选定屏幕区域。
- 使用 RapidFuzz 对 OCR 结果与本地题库进行模糊匹配，当前默认阈值为 40。
- 可调整匹配阈值，并在正式运行前执行一次不会点击的“测试识别”。
- 支持“仅提示答案”和“自动点击答案”两种运行模式；未匹配题目追加到 `data/unmatched_questions.txt`。
- 支持两种选区方式：选择窗口后在窗口截图内框选并保存相对坐标；或不绑定窗口，直接在整个屏幕上框选并保存绝对坐标。
- 窗口相对区域可在切换窗口后复用，并根据窗口尺寸变化进行缩放；屏幕绝对区域固定在桌面坐标上。
- OCR、匹配和点击运行在独立 `QThread` 中。

当前 GUI 会递归读取 `data/` 目录下扩展名为 `.txt` 的题库文件，不会加载 `.json` 文件。支持以下两种内容格式：

```json
[
  {"q": "问题内容", "ans": "答案内容"}
]
```

或每行一个 JSON 对象：

```json
{"q": "问题内容", "ans": "答案内容"}
{"q": "另一个问题", "ans": "另一个答案"}
```

OCR 页面还提供本地题库快速查询，支持中文关键字和已导入题库的拼音首字母索引。公开题库导入文件为 `data/qqsg_public_question_bank.txt`，每条记录保留来源字段；导入脚本为 `tools/import_question_bank.py`。网站题库仅用于补充缺失题目；同一题目出现答案冲突时，原有本地题库答案优先。普通文本答案只显示，只有答案严格为 A/B 时才允许自动点击。

### 行脚洞口助手

- 选择一个 QQ 三国窗口后，按原网站状态机持续识别行脚第一画面和地图画面。
- 每轮先以 `xx.png` 定位游戏锚点，并根据原始锚点 `(41, 92)` 计算五个固定取色点的偏移。
- 状态 1 每三轮检测一次 `xj1.png`；进入状态 3 后最多等待 `xj2.png` 十轮，再按原网站颜色分支判断 1–6 号洞口。
- 模板和坐标严格保持原始像素尺寸，不执行分辨率缩放。
- 可调整模板阈值和颜色阈值。
- 检测时显示本轮实际识别画面，并逐轮输出截图方式、图片尺寸、模板分数与位置、每个颜色点的实际值、色差和最终判定原因。
- 优先使用窗口句柄后台截图以避免遮挡；游戏不支持后台截图时会回退到屏幕截图，并在诊断日志中明确提示。
- 只读取窗口画面，不执行鼠标或键盘操作。
- 模板保存在 `data/templates/travel/`，来源记录在项目文档和题库数据中。

### 自动化脚本平台

- 支持扫描、安装和运行带 `plugin.json` 的本地 Python 插件目录或 ZIP。
- 每个插件拥有独立的 `assets/` 资源目录和 `plugin_data/<插件ID>/` 可写空间。
- 插件在独立 Python 子进程运行，通过本地 JSON-RPC 调用宿主自动化 SDK，异常不会直接拖垮 PyQt 主界面。
- SDK 第一版提供窗口绑定、前后台截图、窗口/客户区坐标、OpenCV 找图、RGB/BGR 取色、颜色比较、前后台键鼠和 JSON 存储。
- 支持模拟运行；模拟模式会执行截图和识别，但不会发送真实键鼠输入。
- 脚本页面显示实时截图、结构化 SDK 调用耗时、步骤日志和调试变量。
- 每次运行在插件数据目录下生成独立的 `run.log`、`events.jsonl` 和配置快照。
- 全局紧急停止快捷键为 `Ctrl+Shift+F12`。
- 内置 `plugins/com.searchcat.example/` 示例插件；开发说明见 `docs/plugin_sdk.md`。
- 内置可校准的 `plugins/com.searchcat.qqsg.official_task/` 官爵任务插件，支持前后台输入、任务步骤数、寻路等待、坐标回退和可选按钮模板。

### 高级连点器

- 鼠标模式：左键、右键、中键、双击和三连击。
- 键盘模式：按指定间隔循环发送按键或组合键。
- 支持固定坐标、当前位置、随机偏移和最大执行次数。
- 支持位置预设和基础脚本录制/回放。

`最大次数` 为 0 时表示不限制次数。

### 窗口按键

- 选择一个目标窗口并循环发送按键序列。
- 支持普通前台模式和 Win32 后台消息模式。
- 按键序列使用 `->` 分隔步骤，使用 `-` 表示组合键，例如：

```text
ctrl-a->b->space
```

### 坐标助手

- 选择目标窗口后记录相对窗口的点坐标或矩形区域。
- 配置保存到 `data/ui_coords.json`。
- 支持查看和删除已保存坐标。

### YOLO 目标检测

- 加载 Ultralytics YOLO `.pt` 模型并检测指定屏幕区域。
- 可配置置信度和检测间隔。
- 可按类别名称自动点击置信度最高的目标。

模型文件不包含在仓库中，需要自行准备。

## 环境要求

- Windows 10/11
- Python 3.10+
- Visual C++ x64 Redistributable
- PaddlePaddle 2.6.0 当前按 CPU 版本配置
- 麦克风相关依赖只供尚未接入 GUI 的 `feature/audio_feature.py` 使用

## 安装

```powershell
python -m venv .venv
.venv\Scripts\pip.exe install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

PyAudio 在部分 Windows/Python 组合上可能需要使用预编译 wheel。如果不使用未接入界面的语音模块，可以在本地环境中按需处理该依赖。

## 运行

GUI 是当前主要入口：

```powershell
python gui.py
```

仓库也保留了早期命令行答题入口：

```powershell
python main.py
```

命令行入口包含固定窗口尺寸和截图比例，更适合特定原始场景，不是通用配置界面。

## GUI 基本操作

1. 从左侧常驻功能栏选择功能。
2. OCR 模式下可以选择窗口后框选窗口区域，也可以选择“全屏框选模式”后直接框选桌面区域。
3. 点击“测试识别”，根据识别结果调整匹配阈值。
4. 选择“仅提示答案”或“自动点击答案”。
5. 点击“启动 (Home)”，或按 Home 键启动当前功能；再次操作即可停止。
6. OCR 结果显示在右侧专用结果栏；其他功能在各自页面内显示状态或结果。

窗口选择器会分别列出同名窗口，只显示自动编号和进程 ID。选择列表项后可查看窗口左上角的人物信息区域，并可使用“定位窗口”确认目标；预览优先通过窗口句柄抓取，不依赖窗口在屏幕上处于最前方。

首次运行会在当前工作目录创建或读取 `license.json`。试用许可证过期后，GUI 会禁用功能入口。

## 构建可执行文件

先在 `.venv` 中安装完整依赖和 PyInstaller，然后执行：

```powershell
.venv\Scripts\pip.exe install pyinstaller
.venv\Scripts\pyinstaller.exe .\gui.spec --noconfirm
```

输出目录：

```text
dist/gui/gui.exe
```

当前 `gui.spec` 显式收集 PaddleOCR、PaddlePaddle 和部分图像处理依赖。构建路径以仓库根目录下的 `.venv` 为前提。

## 项目结构

```text
search_cat/
├── gui.py                         # GUI 入口、许可证和功能切换
├── main.py                        # 早期命令行 OCR 答题入口
├── gui.spec                       # PyInstaller 配置
├── requirements.txt
├── core/
│   ├── ocr.py                     # PaddleOCR 封装
│   ├── winhandler.py              # 窗口选择、移动和截图
│   └── winoperator.py             # 鼠标、键盘、预设和脚本操作
├── feature/
│   ├── ocr_feature.py
│   ├── mouse_clicker_feature.py
│   ├── window_key_feature.py
│   ├── coord_helper_feature.py
│   ├── travel_feature.py
│   ├── yolo_feature.py
│   └── audio_feature.py           # 尚未接入主 GUI
├── tools/
│   └── coord_helper.py
├── data/                          # 题库、坐标和运行产生的数据
└── icon/
```

## 当前限制

- 仅支持 Windows，并依赖 Win32 API、全局键盘钩子和屏幕坐标。
- OCR 自动点击必须绑定目标窗口；全屏框选模式支持测试和仅提示识别，不执行自动点击。
- 切换窗口时只适合复用布局相近的相对区域。
- 部分坐标和窗口尺寸针对原始使用场景写死，在不同分辨率或 DPI 缩放下需要重新选择区域。
- Home 是全局快捷键；使用自动操作前应确保当前选中的功能和目标窗口正确。
- `license.json` 是本地试用状态文件，不是联网许可证系统。
- 项目目前没有正式自动化测试套件。
- 行脚洞口规则和模板针对网站公开页面当前支持的 QQ 三国界面；游戏 UI 更新后可能需要重新采集模板或校准颜色。

## 开发说明

开发约定、线程模式和代码风格见 [AGENTS.md](AGENTS.md)。本项目仅供学习交流，请遵守目标软件的使用规则，并自行承担自动化操作带来的风险。
