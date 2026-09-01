import os
import sys
from pathlib import Path

os.environ.setdefault("USE_TF", "0")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# src/app.py가 런타임에 최상위 ui/(theme.py 등)를 sys.path에 얹는 것과 똑같이 맞춘다 —
# ui.screens.* 모듈(예: ui/screens/my_recipes.py)이 `from theme import ...`를 쓰므로,
# 이 경로가 없으면 그런 모듈을 import하는 테스트가 ModuleNotFoundError로 깨진다.
UI = ROOT / "ui"
if str(UI) not in sys.path:
    sys.path.insert(0, str(UI))
