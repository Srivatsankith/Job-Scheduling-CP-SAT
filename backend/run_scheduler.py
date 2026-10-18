"""DynamIQ CP-SAT scheduling command line entry point."""
import argparse, json
from pathlib import Path
from config import TASKS_PATH, ELIGIBILITY_PATH, DEFAULT_TIME_LIMIT_SECONDS, DEFAULT_WORKERS, DEFAULT_RANDOM_SEED
from src.cp_sat_scheduler import solve_schedule
from src.export_results import export_schedule
from src.baseline_schedulers import schedule_baseline
from src.data_loader import load_datasets
from src.data_validator import validate_inputs
from src.schema_mapper import SchemaMapping
from src.metrics import calculate_metrics

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tasks",default=str(TASKS_PATH)); ap.add_argument("--eligibility",default=str(ELIGIBILITY_PATH))
    ap.add_argument("--time-limit",type=float,default=DEFAULT_TIME_LIMIT_SECONDS); ap.add_argument("--workers",type=int,default=DEFAULT_WORKERS)
    ap.add_argument("--seed",type=int,default=DEFAULT_RANDOM_SEED); ap.add_argument("--objective",choices=["weighted","makespan","total_tardiness"],default="weighted")
    ap.add_argument("--output",default="results/schedule.csv"); ap.add_argument("--log-search-progress",action="store_true")
    ap.add_argument("--baselines",action="store_true",help="also calculate serial EDD, SPT, priority, and original-pair baselines")
    args=ap.parse_args()
    result=solve_schedule(args.tasks,args.eligibility,time_limit_seconds=args.time_limit,num_workers=args.workers,
                          random_seed=args.seed,objective=args.objective,log_search_progress=args.log_search_progress)
    report={"status":result.status,"metrics":result.metrics,"timings":result.timings,
            "objective_value":result.objective_value,"best_bound":result.best_bound,
            "model_stats":result.model_stats,"validation_errors":result.validation_errors}
    if result.feasible:
        export_schedule(result.schedule,args.output); report["schedule_csv"]=str(Path(args.output).resolve())
    if args.baselines:
        t,e=load_datasets(args.tasks,args.eligibility); t,e=SchemaMapping().rename(t,e); t,e=validate_inputs(t,e)
        report["baselines"]={}
        for rule in ("edd","spt","priority","original"):
            s=schedule_baseline(t,e,rule); report["baselines"][rule]=calculate_metrics(s,"BASELINE")
    print(json.dumps(report,indent=2,default=str))
    return 0 if result.feasible else 2

if __name__=="__main__": raise SystemExit(main())
