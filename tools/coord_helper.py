import json
import sys
import cv2
import numpy as np
from pygetwindow import getWindowsWithTitle
from pynput import mouse
import mss

CONFIG_FILE = "ui_coords.json"

# ---------------- 公共工具函数 ----------------
def get_game_window(title="QQ三国"):
    """获取游戏窗口信息，返回(left, top, width, height)或None"""
    windows = getWindowsWithTitle(title)
    if not windows:
        return None
    w = windows[0]
    return (w.left, w.top, w.width, w.height)

def load_config():
    """读取已有配置"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_config(config):
    """保存配置到json"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"✅ 配置已保存到 {CONFIG_FILE}")

# ---------------- 模式1：点选单个坐标 ----------------
def point_select_mode():
    print("\n=== 点选坐标模式 ===")
    win = get_game_window()
    if not win:
        print("❌ 未找到游戏窗口，请先打开游戏")
        return
    left, top, width, height = win
    print(f"✅ 窗口位置：左{left}, 上{top} | 大小：{width}x{height}")
    print("提示：在游戏窗口点击任意元素，按Ctrl+C停止\n")

    def on_click(x, y, button, pressed):
        if not pressed:
            return
        rel_x = x - left
        rel_y = y - top
        print(f"屏幕坐标({x},{y}) → 窗口相对坐标({rel_x}, {rel_y})")
        name = input("输入元素名称（直接回车跳过）：").strip()
        if name:
            config = load_config()
            config[name] = [rel_x, rel_y]  # 点坐标存为[x,y]
            save_config(config)

    with mouse.Listener(on_click=on_click) as listener:
        try:
            listener.join()
        except KeyboardInterrupt:
            print("\n点选模式已停止")

# ---------------- 模式2：框选区域 ----------------
def region_select_mode():
    print("\n=== 框选区域模式 ===")
    win = get_game_window()
    if not win:
        print("❌ 未找到游戏窗口，请先打开游戏")
        return
    left, top, width, height = win
    print(f"✅ 窗口位置：左{left}, 上{top} | 大小：{width}x{height}")

    # 截取游戏画面
    monitor = {"left": left, "top": top, "width": width, "height": height}
    with mss.mss() as sct:
        screenshot = np.array(sct.grab(monitor))
        frame = cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)

    # 框选全局变量
    drawing = False
    ix, iy = -1, -1
    fx, fy = -1, -1

    def draw_rect(event, x, y, flags, param):
        nonlocal drawing, ix, iy, fx, fy
        if event == cv2.EVENT_LBUTTONDOWN:
            drawing = True
            ix, iy = x, y
            fx, fy = x, y
        elif event == cv2.EVENT_MOUSEMOVE and drawing:
            fx, fy = x, y
        elif event == cv2.EVENT_LBUTTONUP:
            drawing = False
            fx, fy = x, y

    cv2.namedWindow("框选区域（拖框选择，R重置，C确认，Q退出）")
    cv2.setMouseCallback("框选区域（拖框选择，R重置，C确认，Q退出）", draw_rect)

    clone = frame.copy()
    while True:
        img = clone.copy()
        if ix != -1 and fy != -1:
            cv2.rectangle(img, (ix, iy), (fx, fy), (0, 255, 0), 2)
            w, h = abs(fx - ix), abs(fy - iy)
            cv2.putText(img, f"{w}x{h}", (ix, iy - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        cv2.imshow("框选区域（拖框选择，R重置，C确认，Q退出）", img)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('r'):
            ix, iy, fx, fy = -1, -1, -1, -1
            print("已重置选择")
        elif key == ord('c'):
            if ix == -1 or fx == -1:
                print("❌ 请先拖框选择区域")
                continue
            # 计算相对坐标
            x1, x2 = min(ix, fx), max(ix, fx)
            y1, y2 = min(iy, fy), max(iy, fy)
            rel_x1 = x1 - left
            rel_y1 = y1 - top
            rel_w = x2 - x1
            rel_h = y2 - y1
            print(f"\n区域相对坐标：左{rel_x1}, 上{rel_y1}, 宽{rel_w}, 高{rel_h}")
            # 保存
            name = input("输入区域名称（直接回车跳过）：").strip()
            if name:
                config = load_config()
                config[name] = [rel_x1, rel_y1, rel_w, rel_h]  # 区域存为[左,上,宽,高]
                save_config(config)
                break
        elif key == ord('q'):
            print("已退出区域选择")
            break
    cv2.destroyAllWindows()

# ---------------- 模式3：查看已有配置 ----------------
def view_config_mode():
    print("\n=== 已有配置 ===")
    config = load_config()
    if not config:
        print("暂无配置")
        return
    for name, value in config.items():
        if len(value) == 2:
            print(f"【点】{name}：({value[0]}, {value[1]})")
        elif len(value) == 4:
            print(f"【区域】{name}：左{value[0]}, 上{value[1]}, 宽{value[2]}, 高{value[3]}")
        else:
            print(f"【未知】{name}：{value}")

# ---------------- 主菜单 ----------------
def main():
    print("=== QQ三国坐标与区域获取工具 ===")
    while True:
        print("\n请选择功能：")
        print("1. 点选单个坐标（点击元素获取相对坐标）")
        print("2. 框选区域（拖框选择区域获取相对坐标）")
        print("3. 查看已有配置")
        print("4. 退出")
        choice = input("输入选项（1-4）：").strip()
        if choice == "1":
            point_select_mode()
        elif choice == "2":
            region_select_mode()
        elif choice == "3":
            view_config_mode()
        elif choice == "4":
            print("工具已退出")
            sys.exit(0)
        else:
            print("无效选项，请重新输入")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n工具已退出")
    except Exception as e:
        print(f"❌ 错误：{e}")
        sys.exit(1)
