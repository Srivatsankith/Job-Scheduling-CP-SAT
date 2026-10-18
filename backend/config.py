from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
DATA_DIR = BACKEND_DIR / "data"
TASKS_PATH = DATA_DIR / "tasks_dataset.csv"
ELIGIBILITY_PATH = DATA_DIR / "task_operator_resource_eligibility.csv"

DEFAULT_TIME_LIMIT_SECONDS = 60.0
DEFAULT_WORKERS = 8
DEFAULT_RANDOM_SEED = 42
