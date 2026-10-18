"""CSV and Excel input loading."""
from pathlib import Path
import pandas as pd

def load_table(source):
    if isinstance(source, pd.DataFrame): return source.copy()
    path = Path(source)
    if path.suffix.lower() == ".csv": return pd.read_csv(path)
    if path.suffix.lower() in {".xlsx", ".xls"}: return pd.read_excel(path)
    raise ValueError(f"Unsupported input format {path.suffix!r}; use CSV or Excel")

def load_datasets(tasks_path, eligibility_path):
    return load_table(tasks_path), load_table(eligibility_path)
