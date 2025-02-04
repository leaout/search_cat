from PIL import Image, ImageDraw

# 创建一个空白图像，大小为64x64像素，背景为白色
image_size = (64, 64)
image = Image.new("RGB", image_size, "white")
draw = ImageDraw.Draw(image)

# 定义工具图标的颜色
tool_color = "blue"

# 绘制一个简单的扳手形状
# 绘制扳手的手柄
draw.rectangle([20, 10, 24, 50], fill=tool_color)
# 绘制扳手的头部
draw.rectangle([10, 30, 34, 34], fill=tool_color)
draw.rectangle([14, 26, 30, 38], fill=tool_color)

# 保存图像到data/icon.png
image.save("data/icon.png")

print("图标已保存为 data/icon.png")