from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent


def test_dockerfiles_locks_e_contexto_sao_seguros():
    subprocess.run(
        [sys.executable, "scripts/container_smoke.py", "static", "--root", str(ROOT)],
        cwd=ROOT,
        check=True,
    )
