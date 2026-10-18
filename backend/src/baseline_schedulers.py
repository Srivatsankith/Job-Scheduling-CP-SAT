"""Dispatching baselines that queue work by rule and respect resource capacities."""
import pandas as pd

def schedule_baseline(tasks, eligibility, rule="edd", *, unavailable=None, dependencies=None):
    """Dispatch tasks in rule order while allowing independent resources to overlap.

    Original uses the task's original pair when available. Priority ranks numeric
    values ascending (so priority 1 precedes 2, 3, 4, 5 in this dataset).
    """
    rule=rule.lower()
    if rule not in {"edd","spt","fcfs","priority","original"}: raise ValueError("rule must be edd, spt, fcfs, priority, or original")
    by_task={k:g.to_dict("records") for k,g in eligibility.groupby("task_id")}
    records=tasks.to_dict("records")
    if rule=="edd": records.sort(key=lambda t:(t["due"],t["arrival"],t["task_id"]))
    elif rule=="spt": records.sort(key=lambda t:(min(a["process_time"] for a in by_task[t["task_id"]]),t["arrival"],t["due"],t["task_id"]))
    elif rule=="fcfs": records.sort(key=lambda t:(t["arrival"],t.get("sequence", t["task_id"])))
    elif rule=="priority":
        rank={"critical":0,"high":1,"medium":2,"low":3}
        records.sort(key=lambda t:(rank.get(str(t.get("priority", "")).strip().lower(), int(t["priority"]) if str(t.get("priority", "")).isdigit() else 99),t["due"],t["arrival"],t["task_id"]))
    else: records.sort(key=lambda t:(t["arrival"],t["due"],t["task_id"]))
    pending=list(records); output=[]; end_by_task={}
    def placement(task, alternative):
        candidate=max(int(task["arrival"]), max((end_by_task.get(prior,0) for prior in (dependencies or {}).get(task["task_id"],[])), default=0))
        operator=alternative["operator"]; machine=alternative["resource"]
        duration=int(alternative["process_time"])
        operator_blocks=[*(unavailable or {}).get("operator",{}).get(operator,[])]
        operator_blocks += [(int(row["start"]),int(row["end"])) for row in output if row["operator"]==operator]
        machine_blocks=[*(unavailable or {}).get("resource",{}).get(machine,[])]
        machine_blocks += [(int(row["start"])-int(row.get("setup_minutes",0)),int(row["end"])) for row in output if row["resource"]==machine]
        for _ in range(len(operator_blocks)+len(machine_blocks)+len(output)+3):
            previous=max((row for row in output if row["resource"]==machine and int(row["end"])<=candidate),key=lambda row:int(row["end"]),default=None)
            setup=int(alternative.get("setup_time",0))
            if previous:
                first=str(previous.get("operation","")).casefold(); second=str(alternative.get("operation","")).casefold()
                transition=(alternative.get("setup_times",{}) or {}).get(f"{first}->{second}",setup)
                setup=max(setup,int(transition))
            process_start=candidate+setup
            machine_collision=next(((a,b) for a,b in sorted(machine_blocks) if candidate < b and a < process_start+duration),None)
            operator_collision=next(((a,b) for a,b in sorted(operator_blocks) if process_start < b and a < process_start+duration),None)
            if machine_collision is None and operator_collision is None: return process_start,setup
            candidate=max(candidate+1,*[collision[1] for collision in (machine_collision,operator_collision) if collision is not None])
        raise ValueError(f"No available time window for task {task['task_id']} on the selected resource pair")
    while pending:
        ready=[task for task in pending if all(prior in end_by_task for prior in (dependencies or {}).get(task["task_id"],[]))]
        if not ready: raise ValueError("task dependencies contain a cycle or unresolved predecessor")
        t=ready[0]; pending.remove(t)
        choices=by_task[t["task_id"]]
        if rule=="original" and t.get("original_operator") and t.get("original_resource"):
            orig=[a for a in choices if a["operator"]==str(t["original_operator"]) and a["resource"]==str(t["original_resource"])]
            if orig: choices=orig
        a=min(choices,key=lambda x:(placement(t,x)[0],x["process_time"],x["operator"],x["resource"]))
        start,setup_minutes=placement(t,a)
        end=start+int(a["process_time"]); end_by_task[t["task_id"]]=end
        if t.get("hard_due") and end>int(t["due"]): raise ValueError(f"task {t['task_id']} cannot meet its hard due time")
        tardy=max(0,end-int(t["due"]))
        output.append({"task_id":t["task_id"],"start":start,"end":end,"duration":int(a["process_time"]),
          "operator":a["operator"],"resource":a["resource"],"due":int(t["due"]),"tardiness":tardy,
          "setup_minutes":setup_minutes,"estimated_cost":int(a.get("cost",0)),"operation":a.get("operation",t.get("operation","")),"status":"late" if tardy else "on_time"})
    return pd.DataFrame(output)
