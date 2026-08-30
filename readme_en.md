[简体中文](readme.md) | English

# Search Cat

Search Cat is a Windows-only desktop automation utility. The current GUI combines OCR-based question answering, mouse/keyboard repetition, repeated key input to a selected window, coordinate capture, and YOLO object detection. The Home key starts or stops the feature currently selected in the GUI.

> This document reflects the implementation currently present in the repository. The application can generate mouse and keyboard input; test all coordinates, keys, and recognition results in a safe window first.

## Implemented features

### OCR search

- Uses PaddleOCR 2.7 with the Chinese model to recognize a selected screen region.
- Uses RapidFuzz to match recognized text against local question data. The current default threshold is 40.
- Provides an adjustable threshold and a one-shot test that never clicks.
- Offers answer-display-only and automatic-click modes.
- Supports two selection modes: select inside a target-window screenshot and store relative coordinates, or bind no window and select an absolute region on the whole desktop.
- Relative window regions can be reused and scaled after switching windows; absolute screen regions remain fixed to desktop coordinates.
- Appends unmatched text to `data/unmatched_questions.txt`.
- Runs capture, OCR, matching, and clicking in a dedicated `QThread`.

The GUI recursively loads only `.txt` files below `data/`; `.json` files are currently ignored. A question file may contain a JSON array:

```json
[
  {"q": "Question", "ans": "Answer"}
]
```

or one JSON object per line:

```json
{"q": "Question", "ans": "Answer"}
{"q": "Another question", "ans": "Another answer"}
```

The OCR page also provides manual local-bank search using Chinese keywords or imported pinyin initials. Public records are stored in `data/qqsg_public_question_bank.txt` with source metadata and can be regenerated with `tools/import_question_bank.py`. When the same question has conflicting answers, the website answer takes precedence over the older local answer. Text answers are display-only; automatic clicking is enabled only for exact A/B answers.

### Travel entrance assistant

- Monitors a selected QQSG window for the first travel scene and map scene.
- Uses local OpenCV templates and relative-window color samples to infer entrances 1–6.
- Configurable template and color thresholds.
- Read-only: it does not generate mouse or keyboard input.
- Templates are stored under `data/templates/travel/`.

### Advanced clicker

- Mouse modes: left, right, middle, double, and triple click.
- Keyboard mode for repeated keys or key combinations.
- Fixed/current coordinates, random offset, and a maximum execution count.
- Position presets and basic script recording/playback.

A maximum count of `0` means unlimited execution.

### Window key input

- Repeatedly sends a key sequence to a selected window.
- Supports foreground input and Win32 background-message mode.
- Separates steps with `->` and combination keys with `-`, for example:

```text
ctrl-a->b->space
```

### Coordinate helper

- Records points or rectangular regions relative to a selected window.
- Saves configuration to `data/ui_coords.json`.
- Lists and deletes saved coordinates.

### YOLO detection

- Loads an Ultralytics YOLO `.pt` model and detects objects in a selected screen region.
- Configurable confidence threshold and detection interval.
- Can automatically click the highest-confidence detection for specified class names.

Model files are not included in this repository.

## Requirements

- Windows 10/11
- Python 3.10+
- Visual C++ x64 Redistributable
- PaddlePaddle 2.6.0, currently configured for CPU use
- Microphone dependencies are used only by `feature/audio_feature.py`, which is not connected to the main GUI

## Installation

```powershell
python -m venv .venv
.venv\Scripts\pip.exe install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

PyAudio may require a prebuilt wheel on some Windows/Python combinations. If you do not use the currently unconnected audio module, handle that optional dependency as appropriate for your local environment.

## Running

The GUI is the primary entry point:

```powershell
python gui.py
```

An older command-line answering flow is also retained:

```powershell
python main.py
```

The CLI uses fixed window dimensions and capture ratios intended for the original scenario; it is not a general configuration interface.

## Basic GUI workflow

1. Select a feature from the persistent left sidebar.
2. In OCR mode, either select a window and draw inside it, or choose full-screen selection mode and draw directly on the desktop.
3. Run **Test recognition** and adjust the matching threshold from the result.
4. Select answer-only or automatic-click mode.
5. Click **Start (Home)** or press Home to start; repeat the action to stop.
6. OCR uses the dedicated right result panel; other features show status or output inside their own pages.

The window picker lists same-title windows separately using only an automatic number and process ID. It previews the top-left character-information area through the window handle and provides a locate action; the preview does not require the target window to be in front.

On first launch, the application creates or reads `license.json` in the current working directory. The GUI disables its feature controls after the local trial expires.

## Building an executable

Install all dependencies and PyInstaller in `.venv`, then run:

```powershell
.venv\Scripts\pip.exe install pyinstaller
.venv\Scripts\pyinstaller.exe .\gui.spec --noconfirm
```

Output:

```text
dist/gui/gui.exe
```

The current `gui.spec` explicitly collects PaddleOCR, PaddlePaddle, and related image-processing dependencies and assumes a `.venv` directory at the repository root.

## Project layout

```text
search_cat/
├── gui.py                         # GUI entry point, license, feature switching
├── main.py                        # Legacy command-line OCR flow
├── gui.spec                       # PyInstaller configuration
├── requirements.txt
├── core/
│   ├── ocr.py                     # PaddleOCR wrapper
│   ├── winhandler.py              # Window selection, movement, capture
│   └── winoperator.py             # Mouse, keyboard, presets, scripts
├── feature/
│   ├── ocr_feature.py
│   ├── mouse_clicker_feature.py
│   ├── window_key_feature.py
│   ├── coord_helper_feature.py
│   ├── travel_feature.py
│   ├── yolo_feature.py
│   └── audio_feature.py           # Not connected to the main GUI
├── tools/
│   └── coord_helper.py
├── data/                          # Questions, coordinates, generated data
└── icon/
```

## Current limitations

- Windows only; relies on Win32 APIs, a global keyboard hook, and screen coordinates.
- Automatic OCR clicking requires a target window. Full-screen selection supports testing and answer-display-only recognition.
- Reusing a relative region works best with windows that have a similar layout.
- Some dimensions and coordinates target the original use case and may require reselection under other resolutions or DPI scaling.
- Home is a global shortcut. Confirm the selected feature and target window before enabling automation.
- `license.json` is a local trial-state file, not an online licensing system.
- There is currently no formal automated test suite.
- Travel rules and templates target the currently supported public QQSG interface and may require recalibration after game UI changes.

See [AGENTS.md](AGENTS.md) for development conventions. This project is intended for learning and experimentation; follow the rules of any target software and use automation responsibly.
