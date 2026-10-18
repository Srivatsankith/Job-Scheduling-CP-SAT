"""Independent schedule feasibility checker."""
def validate_schedule(schedule, tasks, eligibility, *, dependencies=None, unavailable=None, allow_unscheduled=False):
    errors=[]
    required={"task_id","start","end","duration","operator","resource","due","tardiness"}
    missing=required-set(schedule.columns)
    if missing: return [f"schedule missing columns: {sorted(missing)}"]
    if schedule.task_id.duplicated().any(): errors.append("schedule has duplicate tasks")
    if (not allow_unscheduled and set(schedule.task_id)!=set(tasks.task_id)) or not set(schedule.task_id).issubset(set(tasks.task_id)):
        errors.append("schedule task set differs from input tasks")
    task_data=tasks.set_index("task_id")
    allowed=set(zip(eligibility.task_id,eligibility.operator,eligibility.resource,eligibility.process_time))
    for row in schedule.itertuples(index=False):
        if row.task_id not in task_data.index: continue
        t=task_data.loc[row.task_id]
        if row.start<t.arrival: errors.append(f"{row.task_id} starts before arrival")
        if row.end!=row.start+row.duration: errors.append(f"{row.task_id} end/duration mismatch")
        if row.due!=t.due: errors.append(f"{row.task_id} due date mismatch")
        if row.tardiness!=max(0,row.end-row.due): errors.append(f"{row.task_id} tardiness mismatch")
        if bool(t.get("hard_due", False)) and row.end>t.due: errors.append(f"{row.task_id} violates its hard due time")
        if (row.task_id,row.operator,row.resource,row.duration) not in allowed: errors.append(f"{row.task_id} is ineligible or has incorrect duration")
    for col in ("operator","resource"):
        for key,group in schedule.groupby(col):
            rows=list(group.itertuples(index=False))
            if col == "resource": rows.sort(key=lambda row: row.start-int(getattr(row,"setup_minutes",0) or 0))
            else: rows.sort(key=lambda row: row.start)
            for a,b in zip(rows,rows[1:]):
                next_start=b.start-int(getattr(b,"setup_minutes",0) or 0) if col=="resource" else b.start
                if next_start<a.end: errors.append(f"{col} {key} overlaps tasks {a.task_id}/{b.task_id}")
                if col=="resource":
                    prior_alt=eligibility[(eligibility.task_id==a.task_id)&(eligibility.resource==a.resource)&(eligibility.operator==a.operator)]
                    next_alt=eligibility[(eligibility.task_id==b.task_id)&(eligibility.resource==b.resource)&(eligibility.operator==b.operator)]
                    if not prior_alt.empty and not next_alt.empty:
                        first_op=str(prior_alt.iloc[0].get("operation","")).casefold()
                        second_op=str(next_alt.iloc[0].get("operation","")).casefold()
                        matrix=next_alt.iloc[0].get("setup_times",{}) or {}
                        setup=max(int(next_alt.iloc[0].get("setup_time",0)),int(matrix.get(f"{first_op}->{second_op}",0)))
                        if b.start<a.end+setup: errors.append(f"machine {key} is missing {setup} minutes of setup between tasks {a.task_id}/{b.task_id}")
    scheduled = set(schedule.task_id)
    for successor, predecessors in (dependencies or {}).items():
        for predecessor in predecessors:
            if successor in scheduled and predecessor not in scheduled:
                errors.append(f"{successor} is scheduled but predecessor {predecessor} is not")
            if successor in scheduled and predecessor in scheduled:
                a=schedule.loc[schedule.task_id==predecessor].iloc[0]
                b=schedule.loc[schedule.task_id==successor].iloc[0]
                if b.start<a.end: errors.append(f"dependency {predecessor} -> {successor} is violated")
    for resource_type, column in (("operator", "operator"), ("resource", "resource")):
        blocked=(unavailable or {}).get(resource_type,{})
        for row in schedule.itertuples(index=False):
            setup=int(getattr(row,"setup_minutes",0) or 0) if column=="resource" else 0
            for left,right in blocked.get(str(getattr(row,column)), []):
                if row.start-setup < right and left < row.end:
                    errors.append(f"{resource_type} {getattr(row,column)} unavailable during task {row.task_id}")
    return errors
