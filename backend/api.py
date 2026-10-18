"""HTTP API and resource registry for the DynamiQ scheduler."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.baseline_schedulers import schedule_baseline
from src.cp_sat_scheduler import solve_schedule
from src.data_validator import DataValidationError
from src.metrics import calculate_metrics
from src.schedule_validator import validate_schedule
from src import mongo_store

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc


class Job(BaseModel):
    id: str = Field(min_length=1)
    task: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    duration_minutes: int = Field(gt=0)
    arrival: datetime | None = None
    due: datetime
    priority: Literal["Critical", "High", "Medium", "Low"] = "Low"
    material: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    allow_late: bool = True


class Operator(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    availability: str = "Available"
    skills: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)


class Machine(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    machine_type: str = Field(min_length=1)
    availability: str = "Available"
    supported_operations: list[str] = Field(default_factory=list)
    supported_materials: list[str] = Field(default_factory=list)
    operating_cost_per_hour: float = Field(default=0, ge=0)


class ScheduleRequest(BaseModel):
    jobs: list[Job] = Field(min_length=1)
    operators: list[Operator] = Field(default_factory=list)
    machines: list[Machine] = Field(default_factory=list)
    objective: Literal["balanced", "tardiness", "makespan", "cost", "workload", "fastest", "deadline"] = "balanced"
    scheduler: Literal["cp_sat", "fcfs", "sjf", "priority"] = "cp_sat"
    priority_policy: Literal["preference", "strict"] = "preference"
    allow_unscheduled: bool = False
    unscheduled_penalty: int = Field(default=1_000_000, ge=1)
    time_limit_seconds: float = Field(default=10, gt=0, le=120)
    num_workers: int = Field(default=4, ge=1, le=32)


class ResourceRecord(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    active: bool = True
    data: dict = Field(default_factory=dict)


class TaskCollection(BaseModel):
    items: list[dict] = Field(default_factory=list)


app = FastAPI(title="DynamiQ Scheduling API", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_credentials=False, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Content-Type"])


@app.on_event("startup")
def initialize_database():
    try:
        mongo_store.initialize()
    except Exception as error:
        raise RuntimeError(f"Could not initialize MongoDB. Check MONGODB_URI and make sure the MongoDB server is running. Details: {error}") from error


def machine_type_operations(machine_type: str) -> set[str]:
    value = machine_type.strip().casefold()
    families = {"cnc machining": ("cnc", "mill", "lathe"), "assembly": ("assembly",), "quality control": ("inspection", "quality", "qc"), "finishing": ("finishing", "finish"), "packaging": ("packaging", "packing"), "welding": ("welding", "welder"), "epoxy": ("epoxy",)}
    return {operation for operation, markers in families.items() if any(marker in value for marker in markers)}


def _minute(value: datetime, origin_minute: int) -> int:
    actual = value.replace(tzinfo=IST) if value.tzinfo is None else value
    return int(actual.astimezone(UTC).timestamp() // 60) - origin_minute


def _dependency_map(jobs):
    known = {job.id for job in jobs}
    deps = {job.id: list(dict.fromkeys(job.dependencies)) for job in jobs}
    for task_id, predecessors in deps.items():
        if task_id in predecessors: raise HTTPException(status_code=422, detail=f"Task {task_id} cannot depend on itself.")
        missing = set(predecessors) - known
        if missing: raise HTTPException(status_code=422, detail=f"Task {task_id} references unknown predecessor(s): {', '.join(sorted(missing))}.")
    visiting, visited = set(), set()
    def visit(node):
        if node in visiting: raise HTTPException(status_code=422, detail="Task dependencies contain a cycle.")
        if node in visited: return
        visiting.add(node)
        for prior in deps[node]: visit(prior)
        visiting.remove(node); visited.add(node)
    for node in deps: visit(node)
    return deps


@app.get("/api/health")
def health():
    try:
        mongo_store.check_connection()
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"MongoDB connection failed: {error}") from error
    return {"status": "ok", "solver": "OR-Tools CP-SAT", "database": "MongoDB"}


@app.get("/api/resources")
def list_resources():
    rows = mongo_store.get_resources()
    return {kind: [{"id": row["id"], "name": row["name"], "active": row["active"], "data": row["data"]} for row in rows if row["kind"] == kind] for kind in ("machines", "operators")}


@app.get("/api/resources/{kind}")
def list_resource_kind(kind: Literal["machines", "operators"], include_inactive: bool = False):
    rows = mongo_store.get_resources(kind)
    return [{"id": row["id"], "name": row["name"], "active": row["active"], "data": row["data"]} for row in rows if include_inactive or row["active"]]


@app.post("/api/resources/{kind}", status_code=201)
def create_resource(kind: Literal["machines", "operators"], resource: ResourceRecord):
    row = resource.model_dump()
    if not mongo_store.save_resource(kind, row, create_only=True): raise HTTPException(status_code=409, detail=f"{kind[:-1].capitalize()} ID already exists.")
    return row


@app.put("/api/resources/{kind}/{resource_id}")
def update_resource(kind: Literal["machines", "operators"], resource_id: str, resource: ResourceRecord):
    if resource.id != resource_id: raise HTTPException(status_code=422, detail="Resource ID cannot be changed.")
    row = resource.model_dump()
    if not mongo_store.save_resource(kind, row): raise HTTPException(status_code=404, detail="Resource not found.")
    return row


@app.patch("/api/resources/{kind}/{resource_id}/deactivate")
def deactivate_resource(kind: Literal["machines", "operators"], resource_id: str):
    if not mongo_store.set_resource_active(kind, resource_id, False): raise HTTPException(status_code=404, detail="Resource not found.")
    return next(row for row in mongo_store.get_resources(kind) if row["id"] == resource_id)


@app.delete("/api/resources/{kind}/{resource_id}")
def delete_resource(kind: Literal["machines", "operators"], resource_id: str):
    if not mongo_store.remove_resource(kind, resource_id): raise HTTPException(status_code=404, detail="Resource not found.")
    return {"deleted": resource_id}


@app.get("/api/tasks")
def list_tasks(): return mongo_store.get_rows("tasks")


@app.put("/api/tasks")
def replace_tasks(collection: TaskCollection):
    try: mongo_store.replace_rows("tasks", "Job ID", collection.items)
    except ValueError as error: raise HTTPException(status_code=422, detail=str(error)) from error
    return {"saved": len(collection.items)}


@app.get("/api/archive")
def list_archived_tasks(): return mongo_store.get_rows("archived_tasks")


@app.put("/api/archive")
def replace_archived_tasks(collection: TaskCollection):
    try: mongo_store.replace_rows("archived_tasks", "Job ID", collection.items)
    except ValueError as error: raise HTTPException(status_code=422, detail=str(error)) from error
    return {"saved": len(collection.items)}


@app.get("/api/schedule/latest")
def latest_schedule(): return mongo_store.get_latest_schedule()


@app.put("/api/schedule/latest")
def save_schedule_state(data: dict):
    mongo_store.save_latest_schedule(data)
    return {"saved": True}


@app.post("/api/schedule")
def create_schedule(request: ScheduleRequest):
    ids = [job.id.strip() for job in request.jobs]
    if any(not item for item in ids) or len({item.casefold() for item in ids}) != len(ids): raise HTTPException(status_code=422, detail="Job IDs must be non-empty and unique.")
    dependencies = _dependency_map(request.jobs)
    machines_all, operators_all = request.machines, request.operators
    machine_ids = [item.id.strip() for item in machines_all]; operator_ids = [item.id.strip() for item in operators_all]
    if len({item.casefold() for item in machine_ids}) != len(machine_ids): raise HTTPException(status_code=422, detail="Machine IDs must be unique.")
    if len({item.casefold() for item in operator_ids}) != len(operator_ids): raise HTTPException(status_code=422, detail="Operator IDs must be unique.")
    machines = [item for item in machines_all if item.availability.casefold() in {"available", "active"}]
    operators = [item for item in operators_all if item.availability.casefold() in {"available", "active"}]
    now = datetime.now(UTC); due_dates = [job.due.replace(tzinfo=IST).astimezone(UTC) if job.due.tzinfo is None else job.due.astimezone(UTC) for job in request.jobs]
    arrivals = [(job.arrival.replace(tzinfo=IST).astimezone(UTC) if job.arrival and job.arrival.tzinfo is None else job.arrival.astimezone(UTC) if job.arrival else now) for job in request.jobs]
    origin = min([now, *due_dates]); origin_minute = int(origin.timestamp() // 60)
    task_rows, eligibility_rows, diagnostic = [], [], {}
    priority_rank = {"Critical": 1, "High": 2, "Medium": 3, "Low": 4}
    for sequence, (job, arrival, due) in enumerate(zip(request.jobs, arrivals, due_dates)):
        effective_arrival = max(arrival, now)
        task_rows.append({"task_id": job.id, "duration": job.duration_minutes, "arrival": max(0, int(effective_arrival.timestamp() // 60)-origin_minute), "due": max(0, int(due.timestamp() // 60)-origin_minute), "priority": priority_rank[job.priority], "sequence": sequence, "hard_due": not job.allow_late})
        op = job.operation.strip().casefold(); compatible_machine = False; compatible_operator = False
        for machine in machines:
            supported = {x.strip().casefold() for x in machine.supported_operations}
            type_ops = machine_type_operations(machine.machine_type)
            if op not in supported or (type_ops and op not in type_ops): continue
            if job.material and machine.supported_materials and job.material.casefold() not in {m.casefold() for m in machine.supported_materials}: continue
            compatible_machine = True
            process_time = job.duration_minutes
            for operator in operators:
                skills = {x.strip().casefold() for x in [*operator.skills, *operator.certifications]}
                required = {job.operation.casefold(), *(skill.strip().casefold() for skill in job.required_skills)}
                if not required.issubset(skills): continue
                compatible_operator = True
                eligibility_rows.append({"task_id": job.id, "operator": operator.id, "resource": machine.id, "process_time": process_time, "eligible": True, "cost": int(round(process_time * machine.operating_cost_per_hour / 60)), "setup_time": 0, "operation": job.operation})
        if not any(row["task_id"] == job.id for row in eligibility_rows):
            reason = "No active machine supports the required operation/material." if not compatible_machine else "No available operator has the required operation skills/certifications."
            diagnostic[job.id] = reason
            if not request.allow_unscheduled: raise HTTPException(status_code=422, detail=f"Job {job.id}: {reason}")
            eligibility_rows.append({"task_id": job.id, "operator": f"__unavailable_operator_{job.id}", "resource": f"__unavailable_machine_{job.id}", "process_time": job.duration_minutes, "eligible": False, "cost": 0, "setup_time": 0, "operation": job.operation})
    unavailable = {"resource": {}, "operator": {}}
    tf, ef = pd.DataFrame(task_rows), pd.DataFrame(eligibility_rows)
    objective = {"balanced":"weighted", "tardiness":"total_tardiness", "makespan":"makespan", "fastest":"fastest", "deadline":"deadline", "cost":"cost", "workload":"workload"}[request.objective]
    selected_name = {"cp_sat":"CP-SAT", "fcfs":"FCFS", "sjf":"SJF", "priority":"Priority"}[request.scheduler]
    solver_details={}
    try:
        if request.scheduler == "cp_sat":
            result = solve_schedule(tf, ef, time_limit_seconds=request.time_limit_seconds, num_workers=request.num_workers, objective=objective, unavailable=unavailable, priority_policy=request.priority_policy, allow_unscheduled=request.allow_unscheduled, unscheduled_penalty=request.unscheduled_penalty, dependencies=dependencies)
            status, selected, metrics, timings = result.status, result.schedule, result.metrics, result.timings
            solver_details={key:metrics[key] for key in ("best_bound","optimality_proven","timeout_reached","objective_value") if key in metrics}
            if result.validation_errors: raise HTTPException(status_code=500, detail={"message":"Independent schedule validation rejected solver output.","errors":result.validation_errors})
        else:
            if request.allow_unscheduled: raise HTTPException(status_code=422, detail="Unscheduled-task penalties are supported by CP-SAT only.")
            selected = schedule_baseline(tf, ef, {"fcfs":"fcfs","sjf":"spt","priority":"priority"}[request.scheduler], unavailable=unavailable, dependencies=dependencies); status="FEASIBLE"; timings={}
            errors=validate_schedule(selected,tf,ef,dependencies=dependencies,unavailable=unavailable)
            if errors: raise HTTPException(status_code=500, detail={"message":"Independent schedule validation rejected baseline output.","errors":errors})
            metrics=calculate_metrics(selected,status)
            metrics["optimality_proven"]=False
            metrics["scheduler_kind"]="HEURISTIC"
    except (DataValidationError, ValueError) as error: raise HTTPException(status_code=422, detail=str(error)) from error
    if status == "INFEASIBLE":
        return {"status":status,"scheduler":selected_name,"reference_time":origin.isoformat(),"schedule":[],"metrics":{"solver_status":status,"scheduled_task_count":0,"unscheduled_task_count":len(request.jobs)},"unscheduled_tasks":[{"job_id":job.id,"reason":diagnostic.get(job.id,"No feasible schedule satisfies dependency and resource constraints.")} for job in request.jobs],"timings":timings,"validation":{"valid":True,"errors":[]}}
    lookup = {job.id:job for job in request.jobs}; op_names={item.id:item.name for item in operators}
    records=selected.to_dict(orient="records")
    rows=[]
    for row in records:
        job=lookup[row["task_id"]]
        rows.append({"job_id":row["task_id"],"task":job.task,"machine":row["resource"],"operator_id":row["operator"],"operator":op_names.get(row["operator"],row["operator"]),"start_minute":int(row["start"]),"end_minute":int(row["end"]),"duration_minutes":int(row["duration"]),"arrival_minute":_minute(job.arrival or now,origin_minute),"due_minute":_minute(job.due,origin_minute),"tardiness_minutes":int(row["tardiness"]),"status":row["status"],"priority":job.priority,"operation":job.operation})
    unscheduled_ids=set(lookup)-{row["job_id"] for row in rows}
    unresolved = status == "UNKNOWN"
    unscheduled=[{"job_id":task_id,"reason":diagnostic.get(task_id,"Solver ended before finding a feasible assignment." if unresolved else "Could not fit within dependencies and resource constraints.")} for task_id in sorted(unscheduled_ids)]
    actual_horizon=max((int(row["end"]) for row in records),default=1)
    actual_available={"resource":{m.id:max(1,actual_horizon) for m in machines},"operator":{o.id:max(1,actual_horizon) for o in operators}}
    metrics=calculate_metrics(selected,status,available_minutes=actual_available,resource_ids=[m.id for m in machines],operator_ids=[o.id for o in operators])
    metrics.update(solver_details)
    late_count=int(selected.tardiness.gt(0).sum()) if "tardiness" in selected else 0
    workload={str(key):int(group.duration.sum()) for key,group in selected.groupby("operator")} if "operator" in selected else {}
    metrics.update({"scheduled_task_count":len(rows),"unscheduled_task_count":len(unscheduled),"unscheduled_task_ids":[x["job_id"] for x in unscheduled],"deadline_performance_percent":round(100*(len(rows)-late_count)/max(1,len(request.jobs)),1),"estimated_operating_cost":int(selected.get("estimated_cost",pd.Series(dtype="int64")).sum()),"operator_workload_minutes":workload})
    return {"status":status,"scheduler":selected_name,"reference_time":origin.isoformat(),"schedule":rows,"metrics":metrics,"unscheduled_tasks":unscheduled,"timings":timings,"validation":{"valid":True,"errors":[]}}
