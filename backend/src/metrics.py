"""Schedule metrics."""
def calculate_metrics(schedule, solver_status=None, objective_value=None, *, available_minutes=None, resource_ids=None, operator_ids=None):
    if schedule.empty:
        return {"makespan":0,"total_tardiness":0,"late_task_count":0,"mean_tardiness":0.0,
                "operator_utilization":{str(key):0.0 for key in (operator_ids or [])},"resource_utilization":{str(key):0.0 for key in (resource_ids or [])},"solver_status":solver_status,"objective_value":objective_value}
    horizon=max(1,int(schedule.end.max()))
    def utilization(col, configured_ids=None):
        result={str(k):float(g.duration.sum()/horizon) for k,g in schedule.groupby(col)}
        for key in configured_ids or []: result.setdefault(str(key),0.0)
        if available_minutes:
            type_key="resource" if col=="resource" else "operator"
            result={key:float(schedule.loc[schedule[col].astype(str)==key,"duration"].sum()/max(1,int(available_minutes.get(type_key,{}).get(key,horizon)))) for key in result}
        return result
    return {"makespan":int(schedule.end.max()),"total_tardiness":int(schedule.tardiness.sum()),
            "late_task_count":int((schedule.tardiness>0).sum()),"mean_tardiness":float(schedule.tardiness.mean()),
            "operator_utilization":utilization("operator",operator_ids),"resource_utilization":utilization("resource",resource_ids),
            "solver_status":solver_status,"objective_value":objective_value}
