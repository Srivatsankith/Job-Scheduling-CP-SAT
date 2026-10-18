"""Google OR-Tools CP-SAT flexible job-shop scheduler."""
from dataclasses import dataclass, field
from decimal import Decimal
from time import perf_counter
from collections import defaultdict
import math
import pandas as pd
from ortools.sat.python import cp_model
from .data_loader import load_table
from .data_validator import validate_inputs
from .schema_mapper import SchemaMapping
from .metrics import calculate_metrics
from .schedule_validator import validate_schedule

@dataclass
class SchedulerResult:
    schedule: pd.DataFrame
    metrics: dict
    status: str
    timings: dict
    objective_value: float | None = None
    best_bound: float | None = None
    model_stats: str = ""
    validation_errors: list = field(default_factory=list)

    @property
    def feasible(self): return self.status in {"OPTIMAL", "FEASIBLE"}

def _integer_weights(weights):
    vals={k:Decimal(str(v)) for k,v in weights.items()}
    if any(v<0 for v in vals.values()) or not any(vals.values()): raise ValueError("objective weights must be nonnegative and not all zero")
    places=max(max(0,-v.as_tuple().exponent) for v in vals.values())
    scale=10**places
    ints={k:int(v*scale) for k,v in vals.items()}
    divisor=math.gcd(*[x for x in ints.values() if x])
    return {k:v//divisor for k,v in ints.items()}

def _as_bool(value):
    return False if pd.isna(value) else bool(value)


def _integer(value, default=0):
    try:
        return default if pd.isna(value) else int(value)
    except (TypeError, ValueError):
        return default


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _text(value):
    return "" if pd.isna(value) else str(value)


def _priority(value):
    ranks = {"critical": 1, "high": 2, "medium": 3, "low": 4}
    text = str(value).strip().casefold()
    if text in ranks:
        return ranks[text]
    try:
        return int(value)
    except (TypeError, ValueError):
        return 99


def solve_schedule(tasks, eligibility, *, time_limit_seconds=60, num_workers=8, random_seed=42,
                   objective="weighted", objective_weights=None, log_search_progress=False,
                   schema_mapping=None, unavailable=None, dependencies=None,
                   allow_unscheduled=False, unscheduled_penalty=1_000_000,
                   priority_policy="preference"):
    """Solve a flexible job-shop schedule with optional resource and calendar rules."""
    if float(time_limit_seconds) <= 0:
        raise ValueError("time_limit_seconds must be positive")
    if int(random_seed) < 0:
        raise ValueError("random_seed must be nonnegative")
    if int(unscheduled_penalty) <= 0:
        raise ValueError("unscheduled_penalty must be positive")
    if priority_policy not in {"preference", "strict"}:
        raise ValueError("priority_policy must be preference or strict")
    supported_objectives = {"weighted", "makespan", "total_tardiness", "cost", "workload", "fastest", "deadline"}
    if objective not in supported_objectives:
        raise ValueError(f"objective must be one of {', '.join(sorted(supported_objectives))}")

    t0 = perf_counter()
    raw_t, raw_e = load_table(tasks), load_table(eligibility)
    load_s = perf_counter() - t0
    mapper = schema_mapping or SchemaMapping()
    raw_t, raw_e = mapper.rename(raw_t, raw_e)
    validation_t = perf_counter()
    tasks, eligibility = validate_inputs(raw_t, raw_e)
    validation_s = perf_counter() - validation_t
    weights = objective_weights or {"makespan": 1, "total_tardiness": 1}
    int_weights = _integer_weights(weights) if objective == "weighted" else {}

    tasks = tasks.reset_index(drop=True)
    eligibility = eligibility.reset_index(drop=True)
    tids = list(tasks.task_id)
    task_index = tasks.set_index("task_id")
    raw_alternatives = {tid: group.to_dict("records") for tid, group in eligibility.groupby("task_id", sort=False)}
    bytask = {
        tid: [alternative for alternative in raw_alternatives.get(tid, []) if _as_bool(alternative.get("eligible", True))]
        for tid in tids
    }
    if not allow_unscheduled and any(not bytask[tid] for tid in tids):
        raise DataValidationError([f"task {tid} has no eligible alternatives" for tid in tids if not bytask[tid]])

    unavailable = unavailable or {}
    dependencies = dependencies or {}
    max_block_end = max(
        (int(end) for groups in unavailable.values() for blocks in groups.values() for _, end in blocks),
        default=0,
    )
    max_setup_by_resource = defaultdict(int)
    for tid in tids:
        for alternative in bytask[tid]:
            resource = alternative["resource"]
            setup_values = [
                _integer(alternative.get("setup_time", 0)),
                *(_integer(value) for value in _mapping(alternative.get("setup_times")).values()),
            ]
            max_setup_by_resource[resource] = max(max_setup_by_resource[resource], *setup_values)
    work_horizon = sum(
        max((int(a["process_time"]) + max_setup_by_resource[a["resource"]] for a in bytask[tid]), default=0)
        for tid in tids
    )
    horizon = max(1, int(tasks.arrival.max()), int(tasks.due.max()), max_block_end) + work_horizon + 1

    build_t = perf_counter()
    model = cp_model.CpModel()
    starts, ends, tardies, unscheduled = {}, {}, {}, {}
    picks_by_task = defaultdict(list)
    operator_intervals, resource_intervals = defaultdict(list), defaultdict(list)
    resource_choices = defaultdict(list)
    operator_load_terms, total_cost_terms, total_duration_terms = defaultdict(list), [], []
    setup_reservations = {}

    operations_by_resource = defaultdict(set)
    transition_max = defaultdict(int)
    for tid in tids:
        for alternative in bytask[tid]:
            resource = alternative["resource"]
            operations_by_resource[resource].add(_text(alternative.get("operation", "")).casefold())
            for key, value in _mapping(alternative.get("setup_times")).items():
                transition_key = str(key).casefold()
                transition_max[(resource, transition_key)] = max(
                    transition_max[(resource, transition_key)], _integer(value)
                )

    # Reserve each alternative's largest possible incoming setup. This keeps
    # setup and downtime constraints linear in the number of alternatives.
    for tid in tids:
        for alternative in bytask[tid]:
            operation = _text(alternative.get("operation", "")).casefold()
            destination_matrix = _mapping(alternative.get("setup_times"))
            incoming = []
            resource = alternative["resource"]
            for source_operation in operations_by_resource[resource]:
                key = f"{source_operation}->{operation}"
                incoming.append(max(transition_max[(resource, key)], _integer(destination_matrix.get(key))))
            setup_reservations[(tid, alternative["operator"], alternative["resource"])] = max(
                [_integer(alternative.get("setup_time", 0)), *incoming]
            )

    for i, tid in enumerate(tids):
        task = task_index.loc[tid]
        start = model.NewIntVar(0, horizon, f"start_{i}")
        end = model.NewIntVar(0, horizon, f"end_{i}")
        starts[tid], ends[tid] = start, end
        task_literals = []
        if allow_unscheduled:
            unscheduled[tid] = model.NewBoolVar(f"unscheduled_{i}")
        for j, alternative in enumerate(bytask[tid]):
            literal = model.NewBoolVar(f"assign_{i}_{j}")
            task_literals.append(literal)
            duration = int(alternative["process_time"])
            setup = setup_reservations[(tid, alternative["operator"], alternative["resource"])]
            model.Add(start >= int(task.arrival) + setup).OnlyEnforceIf(literal)
            operator_interval = model.NewOptionalIntervalVar(
                start, duration, end, literal, f"operator_interval_{i}_{j}"
            )
            machine_interval = model.NewOptionalIntervalVar(
                start - setup, duration + setup, end, literal, f"machine_interval_{i}_{j}"
            )
            operator_intervals[alternative["operator"]].append(operator_interval)
            resource_intervals[alternative["resource"]].append(machine_interval)
            resource_choices[(tid, alternative["resource"])].append(literal)
            picks_by_task[tid].append((literal, alternative))
            operator_load_terms[alternative["operator"]].append(duration * literal)
            total_cost_terms.append(_integer(alternative.get("cost", 0)) * literal)
            total_duration_terms.append(duration * literal)
            if _as_bool(task.get("hard_due", False)):
                model.Add(end <= int(task.due)).OnlyEnforceIf(literal)

        if allow_unscheduled:
            model.AddExactlyOne([*task_literals, unscheduled[tid]])
            model.Add(start == 0).OnlyEnforceIf(unscheduled[tid])
            model.Add(end == 0).OnlyEnforceIf(unscheduled[tid])
        else:
            model.AddExactlyOne(task_literals)

        tardy = model.NewIntVar(0, horizon, f"tardiness_{i}")
        model.AddMaxEquality(tardy, [end - int(task.due), 0])
        tardies[tid] = tardy

    # Keep operators and machines clear during configured breaks and downtime.
    for resource_type, target in (("operator", operator_intervals), ("resource", resource_intervals)):
        for resource_id, intervals in target.items():
            blocked = unavailable.get(resource_type, {}).get(resource_id, [])
            fixed = [
                model.NewFixedSizeIntervalVar(int(left), int(right) - int(left), f"{resource_type}_blocked_{resource_id}_{index}")
                for index, (left, right) in enumerate(blocked) if int(right) > int(left)
            ]
            model.AddNoOverlap([*intervals, *fixed])

    # Dependencies apply only when both jobs are scheduled. With the optional
    # unscheduled policy, a successor cannot be scheduled if a predecessor is not.
    for successor, predecessors in dependencies.items():
        for predecessor in predecessors:
            if successor not in starts or predecessor not in starts:
                continue
            if allow_unscheduled:
                model.Add(unscheduled[successor] >= unscheduled[predecessor])
                model.Add(starts[successor] >= ends[predecessor]).OnlyEnforceIf(
                    [unscheduled[successor].Not(), unscheduled[predecessor].Not()]
                )
            else:
                model.Add(starts[successor] >= ends[predecessor])

    # Strict priority is machine-local. Aggregate alternatives by task/resource
    # rather than creating a constraint for every alternative pair.
    if priority_policy == "strict":
        tasks_by_resource = defaultdict(list)
        for (tid, resource), literals in resource_choices.items():
            uses_resource = model.NewBoolVar(f"uses_{tid}_{resource}")
            model.AddMaxEquality(uses_resource, literals)
            tasks_by_resource[resource].append(
                (tid, uses_resource, _priority(task_index.loc[tid].get("priority", 99)))
            )
        for resource_tasks in tasks_by_resource.values():
            for index, (first_id, first_used, first_priority) in enumerate(resource_tasks):
                for second_id, second_used, second_priority in resource_tasks[index + 1:]:
                    if first_priority < second_priority:
                        model.Add(starts[second_id] >= ends[first_id]).OnlyEnforceIf([first_used, second_used])
                    elif second_priority < first_priority:
                        model.Add(starts[first_id] >= ends[second_id]).OnlyEnforceIf([first_used, second_used])

    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, list(ends.values()))
    total_tardiness = model.NewIntVar(0, horizon * len(tids), "total_tardiness")
    model.Add(total_tardiness == sum(tardies.values()))

    if objective == "makespan":
        primary = makespan
    elif objective in {"total_tardiness", "deadline"}:
        primary = total_tardiness
    elif objective == "cost":
        primary = sum(total_cost_terms)
    elif objective == "fastest":
        primary = sum(total_duration_terms)
    elif objective == "workload":
        operator_max_load = model.NewIntVar(0, horizon * len(tids), "operator_max_load")
        for index, (operator, terms) in enumerate(operator_load_terms.items()):
            load = model.NewIntVar(0, horizon * len(tids), f"operator_load_{index}")
            model.Add(load == sum(terms))
            model.Add(operator_max_load >= load)
        primary = operator_max_load
    else:
        primary = int_weights.get("makespan", 0) * makespan + int_weights.get("total_tardiness", 0) * total_tardiness

    objective_expr = primary
    if allow_unscheduled:
        objective_expr = primary + int(unscheduled_penalty) * sum(unscheduled.values())
    if priority_policy == "preference":
        priorities = {tid: _priority(task_index.loc[tid].get("priority", 99)) for tid in tids}
        lowest_rank = max(priorities.values(), default=1)
        priority_weights = {tid: max(1, lowest_rank - rank + 1) for tid, rank in priorities.items()}
        preference = sum(priority_weights[tid] * ends[tid] for tid in tids)
        preference_bound = horizon * sum(priority_weights.values())
        objective_expr = objective_expr * (preference_bound + 1) + preference
    model.Minimize(objective_expr)

    model_s = perf_counter() - build_t
    invalid = model.Validate()
    model_stats = model.ModelStats()
    if invalid:
        timings = {"loading_seconds": load_s, "validation_seconds": validation_s, "model_building_seconds": model_s, "solving_seconds": 0.0}
        return SchedulerResult(pd.DataFrame(), {}, "MODEL_INVALID", timings, model_stats=model_stats, validation_errors=[invalid])

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.001, float(time_limit_seconds))
    solver.parameters.num_search_workers = max(1, int(num_workers))
    solver.parameters.random_seed = int(random_seed)
    solver.parameters.log_search_progress = bool(log_search_progress)
    solve_t = perf_counter()
    status_code = solver.Solve(model)
    solve_s = perf_counter() - solve_t
    status = solver.StatusName(status_code)
    timings = {"loading_seconds": load_s, "validation_seconds": validation_s, "model_building_seconds": model_s, "solving_seconds": solve_s}
    timeout_reached = status == "UNKNOWN" and solve_s >= float(time_limit_seconds) * 0.9
    if status not in {"OPTIMAL", "FEASIBLE"}:
        return SchedulerResult(
            pd.DataFrame(), {"solver_status": status, "objective_value": None, "timeout_reached": timeout_reached},
            status, timings, model_stats=model_stats,
        )

    rows = []
    selected_alternatives = {}
    unscheduled_ids = []
    for tid in tids:
        if allow_unscheduled and solver.BooleanValue(unscheduled[tid]):
            unscheduled_ids.append(tid)
            continue
        chosen = next(alternative for literal, alternative in picks_by_task[tid] if solver.BooleanValue(literal))
        selected_alternatives[tid] = chosen
        start, end = solver.Value(starts[tid]), solver.Value(ends[tid])
        due = int(task_index.loc[tid].due)
        rows.append({
            "task_id": tid, "start": start, "end": end, "duration": int(chosen["process_time"]),
            "operator": chosen["operator"], "resource": chosen["resource"], "due": due,
            "tardiness": max(0, end - due), "setup_minutes": _integer(chosen.get("setup_time", 0)),
            "estimated_cost": int(round(float(_integer(chosen.get("cost", 0))))),
            "operation": _text(chosen.get("operation", "")), "status": "late" if end > due else "on_time",
        })

    schedule = pd.DataFrame(rows)
    if not schedule.empty:
        for _, group in schedule.groupby("resource"):
            prior = None
            for index in group.sort_values(["start", "end"]).index:
                current_id = schedule.at[index, "task_id"]
                current = selected_alternatives[current_id]
                setup = _integer(current.get("setup_time", 0))
                if prior is not None:
                    prior_op = _text(prior.get("operation", "")).casefold()
                    current_op = _text(current.get("operation", "")).casefold()
                    matrix = _mapping(current.get("setup_times"))
                    setup = max(setup, _integer(matrix.get(f"{prior_op}->{current_op}", 0)))
                schedule.at[index, "setup_minutes"] = setup
                prior = current

    errors = validate_schedule(
        schedule, tasks, eligibility, dependencies=dependencies, unavailable=unavailable,
        allow_unscheduled=allow_unscheduled,
    )
    objective_value = solver.ObjectiveValue()
    metrics = calculate_metrics(schedule, status, objective_value)
    metrics.update({
        "best_bound": solver.BestObjectiveBound(), "optimality_proven": status == "OPTIMAL",
        "timeout_reached": timeout_reached, "unscheduled_task_ids": unscheduled_ids,
        "unscheduled_task_count": len(unscheduled_ids),
    })
    return SchedulerResult(
        schedule, metrics, status, timings, objective_value, solver.BestObjectiveBound(), model_stats, errors
    )
