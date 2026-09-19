"""Make the independent STRATO add-on modules available to bridge tests."""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / 'ftst_strato_mail' / 'app'))
