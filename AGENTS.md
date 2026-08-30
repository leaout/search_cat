# AGENTS.md - Development Guidelines for Search Cat

## Project Overview

Search Cat (搜索猫) is a Windows-only Python desktop application for OCR-assisted answering and desktop automation. The current implementation uses PyQt5 for the GUI, PaddleOCR for Chinese text recognition, RapidFuzz for question matching, Ultralytics YOLO for optional object detection, and Windows APIs for mouse/keyboard automation.

## Build & Run Commands

### Running the Application
```bash
python main.py           # CLI mode
python gui.py            # GUI mode (main entry point)
```

### Building Executable
```bash
pip install pyinstaller
pyinstaller ./gui.spec --noconfirm
```
Output: `dist/gui/gui.exe`

### Virtual Environment Setup
```bash
python -m venv .venv
.venv\Scripts\pip.exe install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### Dependencies (from requirements.txt)
- PyQt5==5.15.9
- pyautogui, opencv-python, pillow, numpy<2
- paddlepaddle==2.6.0 and paddleocr==2.7.0.3
- pywin32==311, pygetwindow, mss
- thefuzz/rapidfuzz, keyboard
- langchain, langchain_community, openai
- ultralytics for YOLO detection

## Code Style Guidelines

### General Conventions
- **Language**: Python 3.10+
- **Encoding**: UTF-8 (use `encoding='utf-8'` for file I/O)
- **Line Length**: Max 120 characters recommended

### Naming Conventions
- **Classes**: PascalCase (e.g., `WindowHandler`, `OCRWorker`)
- **Functions/Variables**: snake_case (e.g., `find_best_match`, `answer_set`)
- **Constants**: UPPER_SNAKE_CASE
- **Private methods**: prefix with `_` (e.g., `_capture_screenshot`)

### Import Order
1. Standard library (time, os, json, etc.)
2. Third-party packages (PyQt5, pyautogui, numpy, etc.)
3. Local modules (core.*, feature.*)

Example:
```python
import time
import json
import os

from PyQt5.QtWidgets import QMainWindow, QWidget
from PyQt5.QtCore import Qt, QTimer

from core.ocr import Ocr
from core.winoperator import WinOperator
from feature.ocr_feature import OCRFeature
```

### Type Hints
Use type hints for function signatures:
```python
def find_best_match(properties: list, query: str, threshold: int = 40) -> dict | None:
    ...
```

### Docstrings
Use Google-style docstrings:
```python
def capture_screenshot(self, filename: str = "screenshot.png") -> str:
    """Capture current window screenshot and save to file.

    Args:
        filename: Path to save the screenshot file.

    Returns:
        Path to the saved screenshot file.
    """
```

### Error Handling
- Use specific exception types
- Log errors with meaningful messages
- Avoid bare `except:` clauses

```python
try:
    result = do_operation()
except ValueError as e:
    print(f"Invalid input: {e}")
except Exception as e:
    print(f"Operation failed: {e}")
```

### GUI Development (PyQt5)
- Use signals/slots for threading (e.g., `pyqtSignal`)
- Initialize heavy objects in worker threads to avoid cross-thread issues
- Use `QMutex` and `QMutexLocker` for thread safety

```python
class OCRWorker(QThread):
    result_ready = pyqtSignal(str, object)
    
    def __init__(self, answer_set, selected_region=None):
        super().__init__()
        self.answer_set = answer_set
```

### File Structure
```
search_cat/
├── main.py              # CLI entry
├── gui.py               # GUI entry (BaseGUI, QSearchApp)
├── core/
│   ├── ocr.py           # OCR functionality
│   ├── winhandler.py    # Window management
│   └── winoperator.py   # Mouse/keyboard automation
├── feature/
│   ├── ocr_feature.py   # OCR UI feature
│   ├── mouse_clicker_feature.py
│   ├── window_key_feature.py
│   ├── coord_helper_feature.py
│   ├── yolo_feature.py
│   └── audio_feature.py # Present but not wired into the main GUI
├── data/                # Question databases
└── icon/                # Application icon
```

### Testing
- This project does **not** have a formal test suite
- To add tests, create `tests/` directory with pytest
- Run single test: `pytest tests/test_ocr.py::test_specific_function`

### Linting (Recommended)
If adding linting, use:
```bash
pip install ruff
ruff check .
ruff format .
```

Or with flake8:
```bash
pip install flake8
flake8 .
```

## Common Development Patterns

### Threading with PyQt5
- Create worker classes inheriting from `QThread`
- Use signals to communicate results to main thread
- Initialize Qt/system resources inside the thread, not in main thread

### Window Selection
```python
handler = WindowHandler()
handler.choose_window()
handler.move_and_resize_window(1390, 10, 527, 970)
operator = WinOperator(handler.window)
```

### Screen Capture
```python
screenshot_data = handler.capture_question_screenshot()
# or
screenshot_data = handler.capture_screenshot_ext(x1, y1, x2, y2)
```

### Answer Matching
```python
from rapidfuzz import fuzz, utils

def find_best_match_simple(properties, query, threshold=40):
    query_clean = utils.default_process(query).strip()
    for prop in properties:
        score = fuzz.QRatio(query_clean, utils.default_process(prop['q']))
        if score >= threshold:
            return prop
    return None
```

## Notes
- This is a Windows-only application
- Requires VC_redist.x64 on Windows
- The GUI currently loads only `.txt` files under `data/`; each file contains either a JSON array or JSON objects per line with `q` and `ans` fields
- `data/database.json` is not loaded by the current GUI implementation
