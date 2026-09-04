def on_load(context):
    context.log('SDK 示例插件已加载')


def on_start(context):
    window = context.windows.current()
    context.log(f"绑定窗口：{window['title']} · PID {window['pid']}")

    with context.step('捕获窗口'):
        frame = context.capture.window(mode=context.config.get('capture_mode', 'auto'))
        context.log(f'截图成功：{frame.width}×{frame.height}，方式 {frame.capture_mode}')

    with context.step('读取颜色'):
        x = int(context.config.get('sample_x', 100))
        y = int(context.config.get('sample_y', 100))
        color = context.vision.get_color(frame, x, y)
        context.debug.watch('sample_color', color)
        context.log(f'坐标 ({x},{y}) 的 RGB：{color}')

    count = context.storage.read_json('run_count.json', 0) + 1
    context.storage.write_json('run_count.json', count)
    context.debug.watch('run_count', count)

    if context.config.get('perform_click', False):
        with context.step('示例点击'):
            result = context.mouse.click(x, y, mode='foreground')
            context.log(f'点击结果：{result}')


def on_stop(context):
    context.log('SDK 示例插件已结束')
