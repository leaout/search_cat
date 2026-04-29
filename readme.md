[English](readme_en.md) | 简体中文
# 搜索猫 (Search Cat)

![icon](icon/icon.png)

一款 Windows 桌面应用，用于搜索辅助和自动化答题。基于截图 OCR 识别题目，自动匹配题库答案，支持多种自动化操作。

## 功能特性

- **OCR 文字识别**：使用轻量级的 ddddocr 引擎，快速识别截图中的文字
- **题库匹配**：基于模糊匹配算法，在本地题库中查找最佳答案
- **窗口自动化**：自动捕获指定窗口内容，模拟鼠标键盘操作
- **GUI 界面**：基于 PyQt5 的图形界面，操作简便
- **多种功能模块**：
  - OCR 识别功能
  - 鼠标自动点击
  - 窗口按键模拟
  - 语音识别输入

## 安装使用

### 环境要求

- Windows 10/11
- Python 3.10+
- VC_redist.x64（Visual C++ 可再发行组件包）

### 快速开始

1. 克隆仓库
```bash
git clone https://github.com/leaout/search_cat.git
cd search_cat
```

2. 创建虚拟环境并安装依赖
```bash
python -m venv .venv
.venv\Scripts\pip.exe install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

3. 运行程序
```bash
python gui.py    # 图形界面模式（推荐）
python main.py   # 命令行模式
```

### 构建可执行文件

```bash
pip install pyinstaller
pyinstaller ./gui.spec --noconfirm
```

输出文件：`dist/gui/gui.exe`

## 技术栈

| 类别 | 技术 |
|------|------|
| GUI 框架 | PyQt5 5.15.9 |
| OCR 引擎 | ddddocr (基于 ONNX Runtime) |
| 自动化 | pyautogui, pywin32, pygetwindow |
| 图像处理 | OpenCV, Pillow |
| 模糊匹配 | RapidFuzz |
| 打包发布 | PyInstaller |

## 项目结构

```
search_cat/
├── gui.py                  # GUI 入口
├── main.py                 # CLI 入口
├── gui.spec                # PyInstaller 配置
├── start.bat               # 启动脚本
├── requirements.txt        # Python 依赖
├── AGENTS.md               # 开发指南
├── core/                   # 核心功能模块
│   ├── ocr.py             # OCR 识别
│   ├── winhandler.py      # 窗口管理
│   └── winoperator.py     # 鼠标键盘操作
├── feature/                # 功能模块
│   ├── ocr_feature.py     # OCR 功能界面
│   ├── mouse_clicker_feature.py
│   └── window_key_feature.py
├── data/                   # 题库数据 (JSON)
├── icon/                   # 应用图标
└── .github/workflows/      # CI/CD 自动化
    └── build.yml          # 自动构建发布
```

## 使用说明

### OCR 识别流程

1. 点击"选择窗口"按钮，选择目标窗口
2. 点击"开始识别"，程序将自动截取窗口内容
3. OCR 识别题目后，自动在题库中搜索匹配答案
4. 支持自动点击/输入答案

### 题库格式

题库文件为 JSON 格式，位于 `data/` 目录：

```json
[
  {
    "q": "问题内容",
    "ans": "答案内容"
  }
]
```

## 自动构建发布

项目使用 GitHub Actions 自动构建：

- 推送到 `main` 分支时自动构建
- 打 `v*` 标签时自动构建并创建 Release
- 构建产物：`SearchCat.zip`（包含 `gui.exe`）

创建新版本：
```bash
git tag v1.5
git push origin v1.5
```

## 开发指南

详见 [AGENTS.md](AGENTS.md)，包含：
- 代码风格规范
- 常用开发模式
- 测试与 lint 配置

## 许可证

本项目仅供学习交流使用。

## 更新日志

### v1.5 (开发中)
- 替换 PaddleOCR 为 ddddocr，减轻依赖体积
- 固定 onnxruntime==1.17.1 和 numpy<2 确保兼容性

### v1.4
- GitHub Actions 自动构建发布
- 修复标签触发问题

### v1.0
- 初始版本发布
.\.venv\Scripts\pip3.10.exe install -r .\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 运行
```
python main.py
```

## pack
```
pip install pyinstaller
pyinstaller ./gui.spec
```