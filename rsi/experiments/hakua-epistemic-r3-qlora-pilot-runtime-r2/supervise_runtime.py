"""Supervise only this explicitly launched pilot and persist its real exit."""
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
import psutil

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT.parent / "hakua-epistemic-r3-qlora-pilot/.venv-cuda/Scripts/python.exe"
logging.basicConfig(level=logging.INFO)

def main():
    run_name = "pilot002"
    receipt_path = ROOT / (run_name + "-exit.json")
    if receipt_path.exists() or (ROOT / "runs" / run_name).exists():
        raise RuntimeError("Refuse to overwrite a prior execution")
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", TOKENIZERS_PARALLELISM="false", HF_HUB_OFFLINE="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    with (ROOT / (run_name + ".log")).open("wb") as output:
        child = subprocess.Popen([str(PYTHON), "-u", "-B", str(ROOT / "pilot_train.py"), "--run-name", run_name], cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        started = datetime.now(timezone.utc).isoformat()
        (ROOT / (run_name + "-launch.json")).write_text(json.dumps({"pid": child.pid, "started_at": started, "run_name": run_name, "timeout_seconds": 900}, indent=2) + "\n", encoding="utf-8")
        timed_out = False
        try:
            returncode = child.wait(timeout=900)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                owned = psutil.Process(child.pid)
                descendants = owned.children(recursive=True)
                for process in reversed(descendants):
                    process.terminate()
                owned.terminate()
                psutil.wait_procs(descendants + [owned], timeout=10)
            except psutil.NoSuchProcess:
                pass
            returncode = child.wait(timeout=30)
    receipt = {"run_name": run_name, "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(), "returncode": returncode, "timed_out": timed_out, "activation_status": "STOP_AND_REPORT", "automatic_promotion_allowed": False}
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    logging.info("Pilot exit recorded: %s", returncode)
    return returncode

if __name__ == "__main__":
    sys.exit(main())
