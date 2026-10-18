"""Write schedules to CSV."""
from pathlib import Path

def export_schedule(schedule, path):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    schedule.to_csv(path,index=False)
    return path
