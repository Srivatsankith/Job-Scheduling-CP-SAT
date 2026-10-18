import unittest
from pathlib import Path
from unittest.mock import patch
import time
import pandas as pd
from ortools.sat.python import cp_model
from src.data_validator import validate_inputs, DataValidationError
from src.cp_sat_scheduler import solve_schedule
from src.baseline_schedulers import schedule_baseline


def inputs():
    tasks = pd.DataFrame([
        {"task_id":"a", "duration":3, "arrival":0, "due":4, "priority":1, "original_operator":"o1", "original_resource":"r1"},
        {"task_id":"b", "duration":2, "arrival":0, "due":2, "priority":2, "original_operator":"o2", "original_resource":"r2"},
    ])
    elig = pd.DataFrame([
        {"task_id":"a", "operator":"o1", "resource":"r1", "process_time":3},
        {"task_id":"a", "operator":"o2", "resource":"r2", "process_time":3},
        {"task_id":"b", "operator":"o1", "resource":"r1", "process_time":2},
        {"task_id":"b", "operator":"o2", "resource":"r2", "process_time":2},
    ])
    return tasks, elig

class TestValidation(unittest.TestCase):
    def test_duplicate_and_missing_alternative_rejected(self):
        t,e=inputs(); t=pd.concat([t,t.iloc[[0]]],ignore_index=True)
        with self.assertRaises(DataValidationError): validate_inputs(t,e)
        t,e=inputs(); e=e[e.task_id!="b"]
        with self.assertRaises(DataValidationError): validate_inputs(t,e)
    def test_all_baselines_are_valid_and_original_pair_is_used(self):
        from src.schedule_validator import validate_schedule
        t,e=inputs(); t,e=validate_inputs(t,e)
        for rule in ("edd","spt","priority","original"):
            schedule=schedule_baseline(t,e,rule)
            self.assertEqual(validate_schedule(schedule,t,e),[])
        original=schedule_baseline(t,e,"original").set_index("task_id")
        for row in t.itertuples(index=False):
            self.assertEqual(original.loc[row.task_id,"operator"],row.original_operator)
            self.assertEqual(original.loc[row.task_id,"resource"],row.original_resource)

    def test_independent_schedule_validator(self):
        from src.schedule_validator import validate_schedule
        t,e=inputs(); t,e=validate_inputs(t,e); s=schedule_baseline(t,e,"edd")
        self.assertEqual(validate_schedule(s,t,e),[])
        s.loc[0,"start"]=-1
        self.assertTrue(validate_schedule(s,t,e))

class TestScheduler(unittest.TestCase):
    def test_unknown_timeout_status_is_reported(self):
        t=pd.DataFrame([{"task_id":"x","duration":2,"arrival":0,"due":10}])
        e=pd.DataFrame([{"task_id":"x","operator":"o","resource":"r","process_time":2}])
        def timeout(*args,**kwargs):
            time.sleep(0.02)
            return cp_model.UNKNOWN
        with patch.object(cp_model.CpSolver,"Solve",side_effect=timeout):
            result=solve_schedule(t,e,time_limit_seconds=0.001,num_workers=1)
        self.assertEqual(result.status,"UNKNOWN")
        self.assertTrue(result.metrics["timeout_reached"])
        self.assertTrue(result.model_stats)
    def test_single_task_arrival_and_tardiness(self):
        t=pd.DataFrame([{"task_id":"x","duration":5,"arrival":7,"due":10}])
        e=pd.DataFrame([{"task_id":"x","operator":"o","resource":"r","process_time":5}])
        result=solve_schedule(t,e,time_limit_seconds=2,num_workers=1)
        self.assertEqual(result.status,"OPTIMAL"); row=result.schedule.iloc[0]
        self.assertEqual((row.start,row.end,row.tardiness),(7,12,2))
    def test_shared_operator_and_resource_conflicts(self):
        for operator, resources in [("o", ["r1","r2"]), (None,["r","r"])]:
            t=pd.DataFrame([{"task_id":"a","duration":2,"arrival":0,"due":20},{"task_id":"b","duration":2,"arrival":0,"due":20}])
            e=pd.DataFrame([
                {"task_id":"a","operator":operator or "o1","resource":resources[0],"process_time":2},
                {"task_id":"b","operator":operator or "o2","resource":resources[1],"process_time":2}])
            result=solve_schedule(t,e,time_limit_seconds=2,num_workers=1)
            self.assertEqual(result.status,"OPTIMAL"); self.assertEqual(result.metrics["makespan"],4)
    def test_parallel_separate_resources(self):
        t=pd.DataFrame([{"task_id":"a","duration":2,"arrival":0,"due":9},{"task_id":"b","duration":2,"arrival":0,"due":9}])
        e=pd.DataFrame([{"task_id":"a","operator":"a","resource":"ra","process_time":2},{"task_id":"b","operator":"b","resource":"rb","process_time":2}])
        result=solve_schedule(t,e,time_limit_seconds=2,num_workers=1)
        self.assertEqual(result.status,"OPTIMAL"); self.assertEqual(result.metrics["makespan"],2)
    def test_priority_order_is_machine_local(self):
        t=pd.DataFrame([
            {"task_id":"low","duration":2,"arrival":0,"due":20,"priority":"Low"},
            {"task_id":"high","duration":2,"arrival":0,"due":20,"priority":"Critical"},
            {"task_id":"other","duration":2,"arrival":0,"due":20,"priority":"Low"},
        ])
        e=pd.DataFrame([
            {"task_id":"low","operator":"op1","resource":"M1","process_time":2},
            {"task_id":"high","operator":"op2","resource":"M1","process_time":2},
            {"task_id":"other","operator":"op3","resource":"M2","process_time":2},
        ])
        result=solve_schedule(t,e,time_limit_seconds=2,num_workers=1,priority_policy="strict")
        rows=result.schedule.set_index("task_id")
        self.assertEqual(result.status,"OPTIMAL")
        self.assertGreaterEqual(rows.loc["low","start"],rows.loc["high","end"])
        self.assertEqual(rows.loc["high","start"],0)
        self.assertEqual(rows.loc["other","start"],0)
    def test_baseline_can_overlap_independent_machine_and_operator_pairs(self):
        t=pd.DataFrame([
            {"task_id":"a","duration":2,"arrival":0,"due":10,"sequence":0},
            {"task_id":"b","duration":3,"arrival":0,"due":10,"sequence":1},
        ])
        e=pd.DataFrame([
            {"task_id":"a","operator":"o1","resource":"M1","process_time":2},
            {"task_id":"b","operator":"o2","resource":"M2","process_time":3},
        ])
        schedule=schedule_baseline(t,e,"fcfs").set_index("task_id")
        self.assertEqual(schedule.loc["a","start"],0)
        self.assertEqual(schedule.loc["b","start"],0)
    def test_ineligible_assignment_not_used(self):
        t=pd.DataFrame([{"task_id":"x","duration":2,"arrival":0,"due":20}])
        e=pd.DataFrame([{"task_id":"x","operator":"allowed","resource":"r","process_time":3}])
        result=solve_schedule(t,e,time_limit_seconds=2,num_workers=1)
        self.assertEqual(result.schedule.iloc[0].operator,"allowed")
    def test_machine_and_operator_downtime_are_respected(self):
        from src.schedule_validator import validate_schedule
        t=pd.DataFrame([{"task_id":"x","duration":3,"arrival":0,"due":30}])
        e=pd.DataFrame([{"task_id":"x","operator":"op","resource":"m","process_time":3}])
        closed={"resource":{"m":[(0,8)]},"operator":{"op":[(8,12)]}}
        result=solve_schedule(t,e,time_limit_seconds=2,num_workers=1,unavailable=closed)
        self.assertEqual(result.status,"OPTIMAL")
        row=result.schedule.iloc[0]
        self.assertGreaterEqual(row.start,12)
        self.assertEqual(validate_schedule(result.schedule,*validate_inputs(t,e),unavailable=closed),[])
    def test_dependencies_and_machine_setup_respect_downtime(self):
        t=pd.DataFrame([{"task_id":"a","duration":3,"arrival":0,"due":40},{"task_id":"b","duration":4,"arrival":0,"due":40}])
        e=pd.DataFrame([{"task_id":"a","operator":"o1","resource":"m","process_time":3,"setup_time":2,"operation":"mill"},{"task_id":"b","operator":"o2","resource":"m","process_time":4,"setup_time":2,"operation":"weld","setup_times":{"mill->weld":5}}])
        result=solve_schedule(t,e,time_limit_seconds=2,num_workers=1,dependencies={"b":["a"]},unavailable={"resource":{"m":[(0,4)]}})
        rows=result.schedule.set_index("task_id")
        self.assertEqual(result.status,"OPTIMAL")
        self.assertGreaterEqual(rows.loc["a","start"]-rows.loc["a","setup_minutes"],4)
        self.assertGreaterEqual(rows.loc["b","start"],rows.loc["a","end"]+5)
    def test_hard_deadline_can_make_schedule_infeasible(self):
        t=pd.DataFrame([{"task_id":"x","duration":5,"arrival":0,"due":3,"hard_due":True}])
        e=pd.DataFrame([{"task_id":"x","operator":"o","resource":"m","process_time":5}])
        self.assertEqual(solve_schedule(t,e,time_limit_seconds=2,num_workers=1).status,"INFEASIBLE")
    def test_unschedulable_tasks_can_be_reported_with_explicit_policy(self):
        t=pd.DataFrame([{"task_id":"x","duration":5,"arrival":0,"due":20}])
        e=pd.DataFrame([{"task_id":"x","operator":"missing","resource":"missing","process_time":5,"eligible":False}])
        result=solve_schedule(t,e,time_limit_seconds=2,num_workers=1,allow_unscheduled=True,unscheduled_penalty=25)
        self.assertEqual(result.status,"OPTIMAL")
        self.assertTrue(result.schedule.empty)
        self.assertEqual(result.metrics["unscheduled_task_ids"],["x"])
    def test_cost_objective_selects_the_lower_cost_alternative(self):
        t=pd.DataFrame([{"task_id":"x","duration":5,"arrival":0,"due":20}])
        e=pd.DataFrame([{"task_id":"x","operator":"o1","resource":"m1","process_time":5,"cost":20},{"task_id":"x","operator":"o2","resource":"m2","process_time":5,"cost":3}])
        result=solve_schedule(t,e,time_limit_seconds=2,num_workers=1,objective="cost")
        self.assertEqual(result.schedule.iloc[0].resource,"m2")
    def test_baseline_respects_dependencies_and_downtime(self):
        t=pd.DataFrame([{"task_id":"a","duration":3,"arrival":0,"due":30},{"task_id":"b","duration":2,"arrival":0,"due":30}])
        e=pd.DataFrame([{"task_id":"a","operator":"o1","resource":"m1","process_time":3},{"task_id":"b","operator":"o2","resource":"m2","process_time":2}])
        rows=schedule_baseline(t,e,"fcfs",dependencies={"b":["a"]},unavailable={"resource":{"m1":[(0,5)]}}).set_index("task_id")
        self.assertGreaterEqual(rows.loc["a","start"],5)
        self.assertGreaterEqual(rows.loc["b","start"],rows.loc["a","end"])
    def test_baseline_and_csv_export(self):
        from src.export_results import export_schedule
        t,e=inputs(); t,e=validate_inputs(t,e); schedule=schedule_baseline(t,e,"edd")
        path=Path(__file__).parent/"_schedule_export_test.csv"
        try:
            export_schedule(schedule,path)
            self.assertEqual(len(pd.read_csv(path)),2)
        finally:
            path.unlink(missing_ok=True)

