# 离线文字图像研究服务

仅处理自行制作或获得授权的测试图片，不接入游戏、脚本平台、屏幕截图或自动点击。
独立进程运行，主GUI不加载模型；监听地址固定127.0.0.1，禁止对公网开放。

上游：[MgArcher/Text_select_captcha](https://github.com/MgArcher/Text_select_captcha)。
此仓库只提供适配器，不复制上游源码和权重。使用前自行核实上游及模型许可，并固定所用commit。
本地目录是可信Python代码，不要使用未知来源的模型或源码。

## 启动

建议单独创建虚拟环境，以免上游依赖影响GUI的PaddleOCR。
准备可信上游源码和model目录中的best_v3.onnx、pre_model_v7.onnx，
在独立环境安装上游依赖后，从本项目根目录启动：

```powershell
python -m research.text_select_service --upstream D:\research\Text_select_captcha
```

启动时输出本次Bearer令牌，每次重启都会改变。首次识别加载模型，耗时包括冷启动。
服务串行推理，最多上传4MiB、400万像素的PNG/JPEG；不接受URL或服务器文件路径。
上传临时图片处理后删除，无上传数据库。Ctrl+C停止服务。

```powershell
curl.exe http://127.0.0.1:8766/health -H "Authorization: Bearer 本次令牌"
curl.exe http://127.0.0.1:8766/recognize -H "Authorization: Bearer 本次令牌" -H "Content-Type: image/png" --data-binary "@D:\research\authorized-test.png"
```

输出包含width、height、points和elapsed_ms，坐标仅为图片内研究结果，不执行任何点击。
错误：401未授权、413上传过大、415类型不支持、400非法图片或请求、503模型加载/推理失败。
不启用CORS。未打包进gui.exe。单元测试使用假模型，不能代表真实识别准确率。
