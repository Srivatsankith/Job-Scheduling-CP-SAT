"""Input validation with aggregated, actionable errors."""
import pandas as pd

TASK_REQUIRED = {"task_id", "duration", "arrival", "due"}
ELIGIBILITY_REQUIRED = {"task_id", "operator", "resource", "process_time"}

class DataValidationError(ValueError):
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("Input validation failed: " + "; ".join(self.errors))

def validate_inputs(tasks, eligibility):
    errors = []
    if tasks.empty: errors.append("tasks dataset is empty")
    if eligibility.empty: errors.append("eligibility dataset is empty")
    missing_t = TASK_REQUIRED - set(tasks.columns)
    missing_e = ELIGIBILITY_REQUIRED - set(eligibility.columns)
    if missing_t: errors.append(f"tasks missing columns: {sorted(missing_t)}")
    if missing_e: errors.append(f"eligibility missing columns: {sorted(missing_e)}")
    if errors: raise DataValidationError(errors)
    if tasks.task_id.isna().any() or (tasks.task_id.astype(str).str.strip() == "").any():
        errors.append("tasks contain blank task IDs")
    if eligibility[["task_id", "operator", "resource"]].isna().any().any():
        errors.append("eligibility contains blank IDs")
    tasks, eligibility = tasks.copy(), eligibility.copy()
    tasks["task_id"] = tasks.task_id.astype(str)
    eligibility["task_id"] = eligibility.task_id.astype(str)
    eligibility["operator"] = eligibility.operator.astype(str)
    eligibility["resource"] = eligibility.resource.astype(str)
    if tasks.task_id.duplicated().any(): errors.append("tasks contain duplicate task IDs")
    if eligibility.duplicated(["task_id", "operator", "resource"]).any():
        errors.append("eligibility contains duplicate task/operator/resource combinations")
    for frame, cols, name in ((tasks, ["duration", "arrival", "due"], "tasks"),
                              (eligibility, ["process_time"], "eligibility")):
        for col in cols:
            values = pd.to_numeric(frame[col], errors="coerce")
            if values.isna().any(): errors.append(f"{name}.{col} has missing or nonnumeric values")
            elif (values < 0).any(): errors.append(f"{name}.{col} contains negative values")
            elif (values != values.round()).any(): errors.append(f"{name}.{col} must use whole minutes")
    tids, etids = set(tasks.task_id), set(eligibility.task_id)
    if tids - etids: errors.append(f"{len(tids-etids)} task(s) have no eligible alternatives")
    if etids - tids: errors.append(f"eligibility references {len(etids-tids)} unknown task ID(s)")
    if {"original_operator", "original_resource"} <= set(tasks.columns):
        known = set(zip(eligibility.task_id, eligibility.operator, eligibility.resource))
        for row in tasks.itertuples(index=False):
            op, res = getattr(row, "original_operator"), getattr(row, "original_resource")
            if pd.notna(op) and pd.notna(res) and (row.task_id, str(op), str(res)) not in known:
                errors.append(f"task {row.task_id} original operator/resource pair is not eligible")
    if (pd.to_numeric(eligibility.process_time, errors="coerce") <= 0).any():
        errors.append("eligibility.process_time must be greater than zero")
    if (pd.to_numeric(tasks.duration, errors="coerce") <= 0).any():
        errors.append("tasks.duration must be greater than zero")
    if errors: raise DataValidationError(errors)
    for col in ["duration", "arrival", "due"]: tasks[col] = pd.to_numeric(tasks[col]).astype("int64")
    eligibility["process_time"] = pd.to_numeric(eligibility.process_time).astype("int64")
    return tasks, eligibility




