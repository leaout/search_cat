from PyQt5.QtWidgets import (QPushButton, QLabel, QHBoxLayout, QVBoxLayout,
                            QGroupBox, QLineEdit, QDoubleSpinBox, QCheckBox,
                            QFileDialog, QTextEdit)
from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
import time
import os
from core.winhandler import WindowHandler
from core.winoperator import Win32Mouse, WinOperator


class YOLOWorker(QThread):
    result_ready = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    status_updated = pyqtSignal(str)
    model_loaded = pyqtSignal(bool)

    def __init__(self, model_path, confidence_threshold=0.5, selected_region=None,
                 interval=1.0, auto_click_enabled=False, target_classes=None):
        super().__init__()
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.selected_region = selected_region
        self.interval = interval
        self.auto_click_enabled = auto_click_enabled
        self.target_classes = target_classes or []

        self._mutex = QMutex()
        self._stop_flag = False

        self.model = None
        self.handler = None
        self.mouse = None

    def stop_worker(self):
        with QMutexLocker(self._mutex):
            self._stop_flag = True
        if self.isRunning():
            self.quit()
            self.wait(3000)

    def set_selected_region(self, region):
        with QMutexLocker(self._mutex):
            self.selected_region = region

    def set_confidence_threshold(self, threshold):
        with QMutexLocker(self._mutex):
            self.confidence_threshold = threshold

    def set_auto_click(self, enabled, target_classes=None):
        with QMutexLocker(self._mutex):
            self.auto_click_enabled = enabled
            if target_classes is not None:
                self.target_classes = target_classes

    def run(self):
        # 在线程内加载模型，避免跨线程问题
        try:
            self.status_updated.emit("正在加载YOLO模型...")
            from ultralytics import YOLO
            self.model = YOLO(self.model_path)
            self.model_loaded.emit(True)
            self.status_updated.emit("模型加载成功")
        except Exception as e:
            self.error_occurred.emit(f"模型加载失败: {str(e)}")
            self.model_loaded.emit(False)
            return

        # 初始化工具
        self.handler = WindowHandler()
        self.mouse = Win32Mouse()

        self.status_updated.emit("开始检测...")

        while True:
            with QMutexLocker(self._mutex):
                if self._stop_flag:
                    break
                region = self.selected_region
                threshold = self.confidence_threshold
                auto_click = self.auto_click_enabled
                targets = list(self.target_classes)

            try:
                # 截图
                if not region:
                    self.status_updated.emit("未选择检测区域")
                    time.sleep(self.interval)
                    continue

                x1, y1, x2, y2 = region
                screenshot = self.handler.capture_screenshot_ext(x1, y1, x2, y2)

                # YOLO 推理
                start_time = time.time()
                results = self.model.predict(source=screenshot, conf=threshold, verbose=False)
                infer_time = time.time() - start_time

                # 解析结果
                detections = []
                if results and len(results) > 0:
                    boxes = results[0].boxes
                    if boxes is not None and len(boxes) > 0:
                        for box in boxes:
                            cls_id = int(box.cls[0].item())
                            conf = float(box.conf[0].item())
                            xyxy = box.xyxy[0].tolist()
                            bx1, by1, bx2, by2 = int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3])
                            class_name = self.model.names.get(cls_id, str(cls_id))

                            # 计算绝对坐标
                            abs_x1 = x1 + bx1
                            abs_y1 = y1 + by1
                            abs_x2 = x1 + bx2
                            abs_y2 = y1 + by2
                            cx = (abs_x1 + abs_x2) // 2
                            cy = (abs_y1 + abs_y2) // 2

                            detections.append({
                                "class_name": class_name,
                                "class_id": cls_id,
                                "confidence": conf,
                                "bbox": (bx1, by1, bx2, by2),
                                "bbox_abs": (abs_x1, abs_y1, abs_x2, abs_y2),
                                "center": (cx, cy)
                            })

                # 发送结果
                self.result_ready.emit(detections)
                self.status_updated.emit(
                    f"检测到 {len(detections)} 个目标, 耗时 {infer_time:.3f}s"
                )

                # 自动点击
                if auto_click and detections and targets:
                    target_set = set(t.strip().lower() for t in targets)
                    matched = [d for d in detections if d["class_name"].lower() in target_set]
                    if matched:
                        # 取置信度最高的
                        best = max(matched, key=lambda d: d["confidence"])
                        cx, cy = best["center"]
                        self.mouse.click(cx, cy)
                        self.status_updated.emit(
                            f"自动点击: {best['class_name']} ({best['confidence']:.1%}) @ ({cx}, {cy})"
                        )

            except Exception as e:
                self.error_occurred.emit(f"检测错误: {str(e)}")

            time.sleep(self.interval)

        # 清理
        self.status_updated.emit("检测已停止")
        self.model = None
        self.handler = None
        self.mouse = None


class YOLOFeature:
    def __init__(self, parent):
        self.parent = parent
        self.group_box = None
        self.running = False
        self.selected_region = None
        self.worker = None

    def create_ui(self):
        self.group_box = QGroupBox("YOLO目标检测")
        layout = QVBoxLayout(self.group_box)

        # 模型路径行
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel('模型路径:'))
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("选择 .pt 模型文件或输入路径")
        model_layout.addWidget(self.model_input)
        self.browse_btn = QPushButton('浏览...')
        self.browse_btn.clicked.connect(self.browse_model)
        model_layout.addWidget(self.browse_btn)
        layout.addLayout(model_layout)

        # 参数行
        param_layout = QHBoxLayout()
        param_layout.addWidget(QLabel('置信度:'))
        self.conf_spin = QDoubleSpinBox()
        self.conf_spin.setRange(0.1, 1.0)
        self.conf_spin.setSingleStep(0.05)
        self.conf_spin.setValue(0.5)
        param_layout.addWidget(self.conf_spin)
        param_layout.addWidget(QLabel('检测间隔:'))
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.1, 10.0)
        self.interval_spin.setSingleStep(0.1)
        self.interval_spin.setValue(1.0)
        self.interval_spin.setSuffix('s')
        param_layout.addWidget(self.interval_spin)
        layout.addLayout(param_layout)

        # 区域选择行
        region_layout = QHBoxLayout()
        self.region_btn = QPushButton('选择区域')
        self.region_btn.clicked.connect(self.choose_region)
        self.region_label = QLabel('未选择区域')
        region_layout.addWidget(self.region_btn)
        region_layout.addWidget(self.region_label)
        layout.addLayout(region_layout)

        # 自动点击行
        click_layout = QHBoxLayout()
        self.auto_click_cb = QCheckBox('自动点击')
        click_layout.addWidget(self.auto_click_cb)
        click_layout.addWidget(QLabel('目标类别:'))
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("逗号分隔，如: button,option")
        click_layout.addWidget(self.target_input)
        layout.addLayout(click_layout)

        # 控制行
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton('启动 (Home)')
        self.start_btn.clicked.connect(self.toggle)
        self.status_label = QLabel('状态: 停止')
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.status_label)
        layout.addLayout(control_layout)

        layout.addWidget(QLabel('检测结果:'))
        self.result_display = QTextEdit()
        self.result_display.setReadOnly(True)
        self.result_display.setMinimumHeight(150)
        self.result_display.setPlaceholderText('检测结果将在这里显示...')
        layout.addWidget(self.result_display)

        self.parent.left_layout.addWidget(self.group_box)

    def browse_model(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.parent, "选择YOLO模型文件",
            os.path.join(os.getcwd(), "models"),
            "YOLO模型 (*.pt);;所有文件 (*)"
        )
        if file_path:
            self.model_input.setText(file_path)

    def choose_region(self):
        operator = WinOperator()
        self.selected_region = operator.select_screen_region()
        if self.selected_region:
            x1, y1, x2, y2 = self.selected_region
            self.region_label.setText(f"({x1},{y1})-({x2},{y2})")
        else:
            self.region_label.setText("未选择区域")

    def toggle(self):
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self):
        model_path = self.model_input.text().strip()
        if not model_path or not os.path.exists(model_path):
            self.status_label.setText('状态: 请选择有效的模型文件')
            return

        if not self.selected_region:
            self.status_label.setText('状态: 请先选择检测区域')
            return

        # 获取参数
        confidence = self.conf_spin.value()
        interval = self.interval_spin.value()
        auto_click = self.auto_click_cb.isChecked()
        target_classes = [t.strip() for t in self.target_input.text().split(',') if t.strip()]

        # 创建并启动 Worker
        self.worker = YOLOWorker(
            model_path=model_path,
            confidence_threshold=confidence,
            selected_region=self.selected_region,
            interval=interval,
            auto_click_enabled=auto_click,
            target_classes=target_classes
        )
        self.worker.result_ready.connect(self.on_result_ready)
        self.worker.error_occurred.connect(self.on_error_occurred)
        self.worker.status_updated.connect(self.on_status_updated)
        self.worker.model_loaded.connect(self.on_model_loaded)

        self.worker.start()
        self.running = True
        self.start_btn.setText('停止 (Home)')
        self.status_label.setText('状态: 启动中...')
        if hasattr(self.parent, 'hotkey_status_label'):
            self.parent.hotkey_status_label.setText("▶ YOLO检测 - 运行中")

    def stop(self):
        if self.worker:
            self.worker.stop_worker()
            self.worker = None
        self.running = False
        self.start_btn.setText('启动 (Home)')
        self.status_label.setText('状态: 停止')
        if hasattr(self.parent, 'hotkey_status_label'):
            self.parent.hotkey_status_label.setText("○ YOLO检测 - 停止")

    def on_result_ready(self, detections):
        if not detections:
            result_text = "未检测到目标"
        else:
            lines = [f"检测到 {len(detections)} 个目标:"]
            lines.append("─" * 30)
            for i, d in enumerate(detections, 1):
                lines.append(
                    f"[{i}] {d['class_name']} ({d['confidence']:.1%}) "
                    f"@ ({d['bbox'][0]},{d['bbox'][1]},{d['bbox'][2]},{d['bbox'][3]})"
                )
            result_text = "\n".join(lines)

        self.result_display.setText(result_text)

    def on_error_occurred(self, error_msg):
        self.status_label.setText(f'状态: {error_msg}')
        self.result_display.setText(f"错误: {error_msg}")

    def on_status_updated(self, status):
        self.status_label.setText(f'状态: {status}')

    def on_model_loaded(self, success):
        if not success:
            self.stop()
