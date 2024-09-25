[English](readme_en.md) | 简体中文
# 搜索猫
## 介绍
搜索猫是一款基于Python的搜索辅助答题软件，可以实现截取屏幕，OCR识别图片文字内容，通过文字内容快速搜索本地词库，给出最佳搜索结果。


## 环境要求
- Python版本 >= 3.10.11

- Windows系统需安装VC_redist.x64

[下载VC_redist.x64](https://answers.microsoft.com/en-us/windows/forum/all/looking-for-microsoft-visual-c-2015-2019-x64-and/0dc7e0f6-96fb-4c96-95f9-6bedae2e9c21)

- 安装所需库
```
.\.venv\Scripts\pip3.10.exe install -r .\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 运行
```
python main.py
```