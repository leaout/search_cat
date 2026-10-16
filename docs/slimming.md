# 第一轮桌面程序瘦身

默认依赖只安装桌面/OCR/自动化部分：`pip install -r requirements.txt`。
历史YOLO与音频实验依赖移到requirements-optional.txt，不删除现有环境中的包。
PaddleOCR自己的传递依赖仍可能包含部分绘图库，不能把清单精简当作实际体积降幅。

主入口不再预加载Torch；PaddleOCR首次实际使用时才导入并创建共享预测器。
打包已排除Torch、YOLO、LLM组件，新增排除Tk运行时；保留Paddle、OpenCV、SciPy。
PaddleOCR导入链仍用到ppstructure，不直接删除该目录。

2026-10-09基线目录dist/release-20261009/gui：约576MiB，ZIP约201MiB。
主要目录：Paddle约149MiB，OpenCV约86MiB，SciPy及其DLL约93MiB。
因此第一轮主要改善源码启动和默认依赖安装；没有保证大幅缩小发布包。
新包需要单独构建和验证后比较，旧发布目录保留不覆盖。

后续可评估ONNX识别后端、可选模型下载与独立OCR进程，但须验证中文识别兼容性，
不能仅为缩小体积替换当前可工作的识别器。本轮未切换识别后端或修改模型。
