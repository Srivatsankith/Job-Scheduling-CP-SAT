# DynamIQ scheduling backend

Standalone manufacturing scheduling backend using Google OR-Tools CP-SAT. It has no Streamlit dependency and reads CSV or Excel inputs.

## Install and run

From this directory, install `requirements.txt`, then run:

```powershell
python run_scheduler.py --time-limit 60 --workers 8 --objective weighted --output results/schedule.csv
```

For dashboard persistence, install and start MongoDB Community Server locally, or provide a MongoDB Atlas URI. Copy `.env.example` to `.env` and set `MONGODB_URI` and `MONGODB_DATABASE` as needed. Install `requirements.txt`; the API checks connectivity and creates its collections and indexes on startup. No SQL schema script is needed. Then run `uvicorn api:app --reload --host 127.0.0.1 --port 8000` from this directory. The React development server proxies `/api` requests to it. The `resources` collection stores machine and operator documents. The `tasks` and `archived_tasks` collections store ordered task documents using a batch pointer so replacement writes become visible together. The `schedule_state` collection stores the latest schedule. MongoDB creates the database on first use. The CSV files remain scheduler benchmark inputs. `GET /api/health` checks connectivity; `POST /api/schedule` accepts jobs with a required operation and arrival/due timestamps, operators with availability and skills, and machines with type, availability, and supported operations. Dashboard timestamps are entered as IST; timezone-naive API timestamps are interpreted as IST. Only available machines that support a job's operation and available operators with the matching skill become eligible alternatives. Recognized machine types further restrict the supported operation families. The selected scheduler returns its own schedule and metrics, assigning compatible resources to each job.

For a container deployment, see the repository-level `README.md`. Docker Compose builds the backend and the production React/Nginx frontend; set Atlas credentials in `backend/.env` before starting it. The API is not authenticated, so keep the deployment private or put it behind an authenticated access layer.

Pass `--tasks` and `--eligibility` to select alternate CSV/XLSX files. `--baselines` also calculates EDD, SPT, priority, and original-pair metrics. Use `--log-search-progress` for CP-SAT logs. Output includes solver status, objective, best bound, loading/validation/model/solve timings, and model statistics. Only OPTIMAL means optimality was proved; FEASIBLE is a valid incumbent without proof. UNKNOWN is a timeout/no-solution status, distinct from INFEASIBLE.

Python interface:

```python
from src.cp_sat_scheduler import solve_schedule
result = solve_schedule(tasks_df, eligibility_df, time_limit_seconds=60)
```

`SchemaMapping` maps internal field names to input column names. Required task fields are task ID, task duration, arrival and due times; required eligibility fields are task ID, operator, resource and alternative process time. The selected alternative's process time determines the actual scheduled duration. Times and durations must be nonnegative whole minutes; alternative process times must be positive. Invalid/duplicate IDs, unknown tasks, tasks without alternatives, duplicate pairs, and invalid original pairs are reported rather than silently removed.

## Model

Each task has integer start and end variables, with start bounded below by arrival. Exactly one eligible alternative is selected unless the explicit unscheduled policy is enabled. Optional intervals protect each selected operator and machine. Task dependencies, hard due times, and higher-priority-first ordering on shared machines are enforced when supplied. Processing uses the task duration as entered. Tardiness is `max(0, end - due)`, and makespan is the maximum scheduled task end.

The default weighted objective is `makespan + total tardiness`. Decimal weights are converted to exact integer coefficients (and common factors removed), so nonzero weights do not round away. Other objectives minimize makespan, total tardiness/deadline delay, estimated operating cost, total processing time, or maximum operator workload. With priority as a preference, the selected objective is optimized first and priority-weighted completion time breaks ties. Strict priority enforces higher-priority-first order for jobs assigned to the same machine. The model jointly chooses among compatible machine/operator alternatives; metrics are reported for the selected schedule.

## Baselines and limits

EDD, SPT and priority baselines dispatch tasks in the corresponding sorted order and assign each task its shortest eligible process-time alternative. Original assignment uses the original eligible operator/resource pair when present. They are deterministic list schedules: each task is placed at the earliest start allowed by its arrival and the selected operator/resource availability, so tasks on distinct operators/resources can overlap. CP-SAT jointly chooses assignments and start times; these baseline results are not hardcoded.

The API also exposes FCFS (arrival time, then submitted order) and SJF (shortest eligible processing time first). Priority rank is Critical, High, Medium, then Low in the dashboard; numeric priorities in the dataset are interpreted in ascending order. These dispatch rules are heuristics. CP-SAT is the only method here that searches against an objective and can report a proven optimum.

The priority baseline orders numeric values ascending, then uses due date and arrival as tie breakers. Current data contains priorities 1–5, though the original request defined 1–3; 4 and 5 therefore follow 1–3 by their numeric ordering and this assumption should be revisited if those values have a different business meaning.

## Validation and tests

Every feasible CP-SAT schedule is checked independently for task coverage, eligibility, durations, arrival times, due/tardiness calculations, and operator/resource conflicts. Run tests with:

```powershell
python -m unittest discover -s tests -v
```

The full dataset contains 4,000 tasks and 100,000 alternatives. This implementation retains all alternatives as optional intervals. Benchmark model construction and solving before relying on this model under production latency limits.

