import { useEffect, useMemo, useState } from "react";
import { findResourceConflicts, formatScheduleTime, getTimeline, naturalSort, validateRows } from "./gantt.js";

const PAGES = ["Overview", "Task Scheduling", "Task Management", "Workforce"];
const OPERATIONS = ["CNC machining", "Assembly", "Quality control", "Finishing", "Packaging", "Welding", "Epoxy"];
const MACHINE_AVAILABILITY = ["Available", "Inactive", "Maintenance", "Offline"];
const OPERATOR_AVAILABILITY = ["Available", "On task", "Break", "Off shift"];
const STARTER_JOBS = [
  { "Job ID": "JOB-1042", Task: "Precision Milling", Operation: "CNC machining", Machine: "CNC-01", Priority: "High", "Duration (min)": 42, Due: todayAt("10:45"), Status: "Running", Progress: 68, Workforce: "Unassigned" },
  { "Job ID": "JOB-1043", Task: "Component Inspection", Operation: "Quality control", Machine: "QC-02", Priority: "Critical", "Duration (min)": 18, Due: todayAt("11:00"), Status: "Queued", Progress: 0, Workforce: "Unassigned" },
  { "Job ID": "JOB-1044", Task: "Assembly Batch A", Operation: "Assembly", Machine: "ASM-01", Priority: "Medium", "Duration (min)": 55, Due: todayAt("11:30"), Status: "Queued", Progress: 0, Workforce: "Unassigned" },
  { "Job ID": "JOB-1045", Task: "Surface Finishing", Operation: "Finishing", Machine: "FIN-03", Priority: "High", "Duration (min)": 35, Due: todayAt("11:15"), Status: "Running", Progress: 34, Workforce: "Unassigned" },
  { "Job ID": "JOB-1047", Task: "Lathe Operation", Operation: "CNC machining", Machine: "CNC-02", Priority: "Medium", "Duration (min)": 48, Due: todayAt("12:00"), Status: "Queued", Progress: 0, Workforce: "Unassigned" },
];
const STARTER_MACHINES = [
  { "Machine ID": "CNC-01", "Machine Name": "Precision CNC Mill", "Machine Type": "CNC", "Availability status": "Available", "Supported operations": ["CNC machining"] },
  { "Machine ID": "QC-02", "Machine Name": "Quality Inspection Station", "Machine Type": "Inspection", "Availability status": "Available", "Supported operations": ["Quality control"] },
  { "Machine ID": "ASM-01", "Machine Name": "Assembly Bench", "Machine Type": "Assembly", "Availability status": "Available", "Supported operations": ["Assembly"] },
  { "Machine ID": "FIN-03", "Machine Name": "Finishing Line", "Machine Type": "Finishing", "Availability status": "Available", "Supported operations": ["Finishing"] },
  { "Machine ID": "CNC-02", "Machine Name": "CNC Lathe", "Machine Type": "CNC", "Availability status": "Available", "Supported operations": ["CNC machining"] },
];

function istParts(date = new Date()) {
  return Object.fromEntries(new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(date).filter((part) => part.type !== "literal").map(({ type, value }) => [type, value]));
}

function todayIST() {
  const parts = istParts();
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function currentTimeIST() {
  const parts = istParts();
  return `${parts.hour}:${parts.minute}`;
}

function currentTimeDisplayIST(date = new Date()) {
  return new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).format(date);
}

function addISTMinutes(date, time, minutes) {
  const [year, month, day] = date.split("-").map(Number);
  const [hour, minute] = time.split(":").map(Number);
  if (![year, month, day, hour, minute].every(Number.isFinite)) return { date, time };
  const shifted = new Date(Date.UTC(year, month - 1, day, hour, minute + minutes));
  return {
    date: [shifted.getUTCFullYear(), String(shifted.getUTCMonth() + 1).padStart(2, "0"), String(shifted.getUTCDate()).padStart(2, "0")].join("-"),
    time: [String(shifted.getUTCHours()).padStart(2, "0"), String(shifted.getUTCMinutes()).padStart(2, "0")].join(":"),
  };
}

function istDateTimeValue(value) {
  const [date, time] = value.split(" ");
  const [year, month, day] = date.split("-").map(Number);
  const [hour, minute] = time.split(":").map(Number);
  return Date.UTC(year, month - 1, day, hour, minute);
}

function newTaskForm() {
  const arrivalDate = todayIST();
  const arrivalTime = currentTimeIST();
  const due = addISTMinutes(arrivalDate, arrivalTime, 120);
  return { id: "", task: "", operation: OPERATIONS[0], priority: "Low", duration: "30", unit: "Minutes", arrivalDate, arrivalTime, dueDate: due.date, dueTime: due.time, material: "", requiredSkills: [], dependencies: [], allowLate: true };
}

function todayAt(time) {
  return `${todayIST()} ${time}`;
}

function inferOperation(task = "") {
  const value = task.toLowerCase();
  if (/weld/.test(value)) return "Welding";
  if (/epoxy/.test(value)) return "Epoxy";
  if (/inspect|quality|qc/.test(value)) return "Quality control";
  if (/assembl/.test(value)) return "Assembly";
  if (/finish|surface/.test(value)) return "Finishing";
  if (/pack/.test(value)) return "Packaging";
  return "CNC machining";
}

function machineOperations(machine) {
  return machine["Supported operations"] || STARTER_MACHINES.find((item) => item["Machine ID"] === machine["Machine ID"])?.["Supported operations"] || OPERATIONS;
}

function operatorSkills(operator) {
  return operator.Skills || [operator["Skill group"]].filter(Boolean);
}

function istDateTimeToISO(value) {
  if (!value) return null;
  return new Date(`${value.replace(" ", "T")}:00+05:30`).toISOString();
}

function useStoredState(_key, initialValue) {
  return useState(initialValue);
}

function downloadCsv(rows, filename) {
  if (!rows.length) return;
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const escape = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const csv = [columns.map(escape).join(","), ...rows.map((row) => columns.map((column) => escape(row[column])).join(","))].join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function Metric({ label, value, foot, icon }) {
  return <article className="metric-card"><div className="metric-label"><span>{icon}</span>{label}</div><div className="metric-value">{value}</div><div className="metric-foot">{foot}</div></article>;
}

function DataTable({ columns, rows, children }) {
  const keyFor = (column) => typeof column === "string" ? column : column.key;
  const labelFor = (column) => typeof column === "string" ? column : column.label;
  return <div className="table-scroll"><table><thead><tr>{columns.map((column) => <th key={keyFor(column)}>{labelFor(column)}</th>)}</tr></thead><tbody>{children ?? rows.map((row, index) => <tr key={`${row[keyFor(columns[0])]}-${index}`}>{columns.map((column) => <td key={keyFor(column)}>{row[keyFor(column)]}</td>)}</tr>)}</tbody></table></div>;
}

function TagInput({ value = [], onChange, placeholder }) {
  const [draft, setDraft] = useState("");
  const addTag = () => {
    const tag = draft.trim();
    if (!tag || value.some((item) => item.toLowerCase() === tag.toLowerCase())) return;
    onChange([...value, tag]);
    setDraft("");
  };
  return <div className="tag-editor">
    <div className="tag-list">{value.map((tag) => <span className="tag-chip" key={tag}>{tag}<button type="button" aria-label={`Remove ${tag}`} onClick={() => onChange(value.filter((item) => item !== tag))}>×</button></span>)}</div>
    <div className="inline-fields"><input value={draft} placeholder={placeholder} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addTag(); } }}/><button type="button" className="secondary-action" onClick={addTag}>Add</button></div>
  </div>;
}

function AccurateGanttChart({ rows = [], referenceTime, schedulerName, solverStatus, selectedId, onSelect, zoom = 1, onZoomChange }) {
  const { valid, warnings } = useMemo(() => validateRows(rows), [rows]);
  const machines = useMemo(() => naturalSort(valid.map((row) => row.Machine)), [valid]);
  const baseTimeline = useMemo(() => getTimeline(valid), [valid]);
  const timeline = { ...baseTimeline, width: baseTimeline.width * zoom, pixelsPerMinute: baseTimeline.pixelsPerMinute * zoom };
  const conflicts = useMemo(() => findResourceConflicts(valid), [valid]);
  const displayWarnings = Number.isFinite(Date.parse(referenceTime)) ? warnings : [...warnings, "Schedule reference time is missing or invalid; absolute times cannot be displayed."];
  const selected = valid.find((row) => row["Job ID"] === selectedId);
  if (!rows.length) return <div className="info-box">No tasks to display for this schedule.</div>;
  return <>
    {displayWarnings.length > 0 && <div className="schedule-warning" role="alert"><strong>Schedule data needs attention</strong>{displayWarnings.map((warning) => <span key={warning}>{warning}</span>)}</div>}
    {conflicts.length > 0 && <div className="schedule-warning conflict-warning" role="alert"><strong>Resource conflicts detected</strong>{conflicts.map((conflict, index) => <span key={`${conflict.resourceType}-${conflict.resource}-${index}`}>{conflict.resourceType} {conflict.resource}: {conflict.jobs.map((row) => row["Job ID"]).join(" / ")} overlap {formatScheduleTime(referenceTime, conflict.startMinute)}–{formatScheduleTime(referenceTime, conflict.endMinute)} IST.</span>)}</div>}
    {!valid.length ? <div className="info-box">No valid task time ranges are available to draw.</div> : <><div className="gantt-toolbar"><span>Timeline zoom</span><button type="button" className="secondary-action" onClick={() => onZoomChange?.(Math.max(.5, zoom / 1.25))} aria-label="Zoom out">−</button><span>{Math.round(zoom * 100)}%</span><button type="button" className="secondary-action" onClick={() => onZoomChange?.(Math.min(4, zoom * 1.25))} aria-label="Zoom in">+</button><button type="button" className="secondary-action" onClick={() => onZoomChange?.(1)}>Reset</button></div><div className="gantt-scroll"><div className="gantt-chart" style={{ "--machine-column-width": "120px", "--timeline-width": `${timeline.width}px`, width: `calc(164px + ${timeline.width}px)` }}>
      <div className="gantt-axis"><div className="gantt-machine-label">Machine</div><div className="gantt-axis-track">{timeline.ticks.map((tick, index) => <span key={`${tick.minute}-${index}`} style={{ left: `${(tick.minute - timeline.first) * timeline.pixelsPerMinute}px` }} title={`${formatScheduleTime(referenceTime, tick.minute, true)} IST`}>{formatScheduleTime(referenceTime, tick.minute, timeline.span >= 1440)}</span>)}</div></div>
      {machines.map((machine) => <div className="gantt-lane" key={machine}><div className="gantt-machine-label">{machine}</div><div className="gantt-track">{timeline.ticks.map((tick, index) => <i aria-hidden="true" className="gantt-gridline" key={`grid-${machine}-${index}`} style={{ left: `${(tick.minute - timeline.first) * timeline.pixelsPerMinute}px` }}/>)}{(() => { const nowMinute=(Date.now()-Date.parse(referenceTime))/60000; return Number.isFinite(nowMinute) && nowMinute>=timeline.first && nowMinute<=timeline.last ? <i className="gantt-now-marker" style={{ left: `${(nowMinute-timeline.first)*timeline.pixelsPerMinute}px` }} title="Current time"/> : null; })()}{valid.filter((row) => row.Machine === machine).map((row) => {
        const left = (row.startMinute - timeline.first) * timeline.pixelsPerMinute;
        const width = (row.endMinute - row.startMinute) * timeline.pixelsPerMinute;
        const category = String(row.Priority).toLowerCase();
        const priorityClass = ["critical", "high", "medium", "low"].includes(category) ? category : "low";
        return <button type="button" className={`gantt-bar gantt-${priorityClass} ${width < 120 ? "gantt-bar-compact" : ""} ${row["Task state"] === "Waiting" ? "gantt-is-waiting" : ""} ${selectedId === row["Job ID"] ? "selected" : ""}`} key={row["Job ID"]} style={{ left: `${left}px`, width: `${width}px` }} title={`${row["Job ID"]} · ${row.Task} · ${formatScheduleTime(referenceTime, row.startMinute, true)}–${formatScheduleTime(referenceTime, row.endMinute, true)} IST`} aria-label={`Show ${row["Job ID"]}, ${row.Task} on ${row.Machine}, ${formatScheduleTime(referenceTime, row.startMinute)} to ${formatScheduleTime(referenceTime, row.endMinute)} IST`} aria-pressed={selectedId === row["Job ID"]} onClick={() => onSelect(selectedId === row["Job ID"] ? null : row["Job ID"])}>{width >= 120 ? <span className="gantt-task-label">{row["Job ID"]} · {row.Task}</span> : width >= 60 ? <span className="gantt-task-label">{row["Job ID"]}</span> : null}</button>;
      })}</div></div>)}
      {selected && <section className="gantt-detail" aria-label="Selected task details"><strong>{selected["Job ID"]} · {selected.Task}</strong><button type="button" className="gantt-detail-close" aria-label="Close task details" onClick={() => onSelect(null)}>×</button><span>Machine: {selected.Machine}</span><span>Operator: {selected.Workforce || "—"}</span><span>Priority: {selected.Priority || "—"}</span><span>Time: {formatScheduleTime(referenceTime, selected.startMinute, true)}–{formatScheduleTime(referenceTime, selected.endMinute, true)} IST</span><span>Actual duration: {selected.endMinute - selected.startMinute} min</span><span>Arrival: {selected["Arrival time"] || "—"}</span><span>Due: {selected.Due || "—"}</span><span>Tardiness: {selected["Tardiness (min)"] ?? "—"} min</span><span>State: {selected["Task state"] || "—"}</span><span>Scheduler: {schedulerName || "—"} ({solverStatus || "status unavailable"})</span></section>}
      <div className="gantt-legend"><span><i className="gantt-swatch gantt-critical"/>Critical priority</span><span><i className="gantt-swatch gantt-high"/>High priority</span><span><i className="gantt-swatch gantt-medium"/>Medium priority</span><span><i className="gantt-swatch gantt-low"/>Low priority</span><span><i className="gantt-swatch gantt-waiting-outline"/>Waiting task (dotted outline)</span></div>
    </div></div></>}
  </>;
}

export default function App() {
  const [page, setPage] = useState("Overview");
  const [jobs, setJobs] = useStoredState("dynamiq.jobs", []);
  const [operators, setOperators] = useStoredState("dynamiq.operators", []);
  const [machines, setMachines] = useStoredState("dynamiq.machines", []);
  const [schedule, setSchedule] = useStoredState("dynamiq.schedule", null);
  const [archived, setArchived] = useStoredState("dynamiq.archived", []);
  const [runs, setRuns] = useStoredState("dynamiq.runs", 0);
  const [lastSchedule, setLastSchedule] = useStoredState("dynamiq.lastSchedule", currentTimeDisplayIST());
  const [databaseReady, setDatabaseReady] = useState(false);
  const [databaseError, setDatabaseError] = useState("");
  const [notice, setNotice] = useState("");
  const [scheduler, setScheduler] = useState("cp_sat");
  const [objective, setObjective] = useState("balanced");
  const [priorityPolicy, setPriorityPolicy] = useState("preference");
  const [allowUnscheduled, setAllowUnscheduled] = useState(false);
  const [unscheduledPenalty, setUnscheduledPenalty] = useState(1000000);
  const [ganttZoom, setGanttZoom] = useState(1);
  const [solving, setSolving] = useState(false);
  const [solverSummary, setSolverSummary] = useState(null);
  const [taskForm, setTaskForm] = useState(newTaskForm);
  const [dueManuallySet, setDueManuallySet] = useState(false);
  const [operatorForm, setOperatorForm] = useState({ id: "", name: "", skills: [OPERATIONS[0]], certifications: [], availability: "Available" });
  const [machineForm, setMachineForm] = useState({ id: "", name: "", type: "", availability: "Available", supportedOperations: [OPERATIONS[0]], supportedMaterials: [], operatingCostPerHour: 0 });
  const [selectedJob, setSelectedJob] = useState("");
  const [selectedScheduleId, setSelectedScheduleId] = useState(null);

  const activeJobs = jobs.filter((job) => job.Status !== "Completed");
  useEffect(() => {
    ["dynamiq.jobs", "dynamiq.operators", "dynamiq.machines", "dynamiq.schedule", "dynamiq.archived", "dynamiq.runs", "dynamiq.lastSchedule", "dynamiq.empty-start.v1"].forEach((key) => localStorage.removeItem(key));
    let disposed = false;
    Promise.all([fetch("/api/tasks"), fetch("/api/archive"), fetch("/api/schedule/latest")]).then(async ([taskResponse, archiveResponse, scheduleResponse]) => {
      if (![taskResponse, archiveResponse, scheduleResponse].every((response) => response.ok)) throw new Error("Could not load saved data from MongoDB.");
      const [savedJobs, savedArchive, savedSchedule] = await Promise.all([taskResponse.json(), archiveResponse.json(), scheduleResponse.json()]);
      if (disposed) return;
      setJobs(savedJobs);
      setArchived(savedArchive);
      if (savedSchedule) {
        setSchedule(savedSchedule.schedule || null);
        setSolverSummary(savedSchedule.solverSummary || null);
        setRuns(savedSchedule.runs || 0);
        setLastSchedule(savedSchedule.lastSchedule || currentTimeDisplayIST());
      }
      setDatabaseReady(true);
    }).catch((error) => { if (!disposed) { setDatabaseError(error.message || "Could not connect to MongoDB."); setNotice(error.message || "Could not connect to MongoDB."); } });
    return () => { disposed = true; };
  }, []);
  useEffect(() => {
    if (!databaseReady) return;
    fetch("/api/tasks", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items: jobs }) }).then((response) => { if (!response.ok) throw new Error(); }).catch(() => setNotice("Could not save tasks to MongoDB."));
  }, [databaseReady, jobs]);
  useEffect(() => {
    if (!databaseReady) return;
    fetch("/api/archive", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items: archived }) }).then((response) => { if (!response.ok) throw new Error(); }).catch(() => setNotice("Could not save completed tasks to MongoDB."));
  }, [databaseReady, archived]);
  useEffect(() => {
    if (!databaseReady) return;
    fetch("/api/schedule/latest", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ schedule, solverSummary, runs, lastSchedule }) }).then((response) => { if (!response.ok) throw new Error(); }).catch(() => setNotice("Could not save schedule details to MongoDB."));
  }, [databaseReady, schedule, solverSummary, runs, lastSchedule]);
  useEffect(() => {
    let disposed=false;
    fetch("/api/resources").then((response) => response.ok ? response.json() : null).then(async (registry) => {
      if (disposed || !registry) return;
      const hydratedMachines=(registry.machines || []).filter((row) => row.active !== false).map((row) => ({ "Machine ID": row.id, "Machine Name": row.name, "Machine Type": "General", "Availability status": "Available", "Supported operations": [], ...(row.data || {}) }));
      const hydratedOperators=(registry.operators || []).filter((row) => row.active !== false).map((row) => ({ "Operator ID": row.id, Operator: row.name, Availability: "Available", Skills: [], Certifications: [], ...(row.data || {}) }));
      setMachines(hydratedMachines);
      setOperators(hydratedOperators);
    }).catch(() => {});
    return () => { disposed=true; };
  }, []);
  useEffect(() => {
    if (activeJobs.length === 0) {
      setSchedule(null);
      setSolverSummary(null);
      setSelectedScheduleId(null);
    }
  }, [activeJobs.length]);
  const running = jobs.filter((job) => job.Status === "Running").length;
  const queued = jobs.filter((job) => job.Status === "Queued").length;
  const completionColumns = ["Sequence", "Job ID", "Task", "Machine", "Workforce", "Priority", "Duration (min)", { key: "Arrival time", label: "Arrival (IST)" }, { key: "Due", label: "Due (IST)" }, "Recommended start"];
  const scheduleColumns = ["Sequence", "Job ID", "Task", "Machine", "Assigned operator", "Priority", "Arrival (IST)", "Start time", "End time", "Duration (min)", "Due (IST)", "Tardiness (min)", "Scheduling status"];
  const availableOperators = operators.filter((operator) => operator.Availability === "Available" && operatorSkills(operator).length > 0);
  const noticeMessage = useMemo(() => notice, [notice]);

  const showNotice = (message) => {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 3500);
  };

  const persistResource = async (kind, id, name, data, method = "PUT") => {
    try {
      const path = method === "POST" ? `/api/resources/${kind}` : `/api/resources/${kind}/${encodeURIComponent(id)}`;
      const cleanedData = { ...data };
      const obsoleteFields = kind === "machines"
        ? ["processingFactor", "processingFactors", "setupMinutes", "setupTimes", "workingDays", "shiftStart", "shiftEnd", "breaks", "downtime"]
        : ["speedFactor", "workingDays", "shiftStart", "shiftEnd", "breaks", "downtime"];
      obsoleteFields.forEach((field) => delete cleanedData[field]);
      const response = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, name, active: true, data: cleanedData }) });
      if (!response.ok) throw new Error("Could not save resource to MongoDB.");
      return true;
    } catch {
      setNotice("Could not save resource to MongoDB.");
      return false;
    }
  };

  const updateArrivalTime = (field, value) => {
    setTaskForm((current) => {
      const updated = { ...current, [field]: value };
      if (dueManuallySet) return updated;
      const due = addISTMinutes(updated.arrivalDate, updated.arrivalTime, 120);
      return { ...updated, dueDate: due.date, dueTime: due.time };
    });
  };

  const makeSchedule = async () => {
    if (!activeJobs.length) return showNotice("Add at least one job before scheduling.");
    if (!availableOperators.length) return showNotice("Add at least one available operator before scheduling.");
    if (!machines.length) return showNotice("Add at least one machine resource in Workforce before scheduling.");
    setSolving(true);
    try {
      const response = await fetch("/api/schedule", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scheduler, objective, priority_policy: priorityPolicy, allow_unscheduled: allowUnscheduled, unscheduled_penalty: Number(unscheduledPenalty),
          jobs: activeJobs.map((job) => ({ id: job["Job ID"], task: job.Task, operation: job.Operation || inferOperation(job.Task), arrival: istDateTimeToISO(job.Arrival), priority: job.Priority, duration_minutes: Number(job["Duration (min) "] || job["Duration (min)"]), due: istDateTimeToISO(job.Due), material: job.Material || null, required_skills: job["Required skills"] || [], dependencies: job.Dependencies || [], allow_late: job["Allow late"] !== false })),
          operators: operators.map((operator) => ({ id: operator["Operator ID"], name: operator.Operator, availability: operator.Availability, skills: operatorSkills(operator), certifications: operator.Certifications || [] })),
          machines: machines.map((machine) => {
            const legacyProfile = STARTER_MACHINES.find((item) => item["Machine ID"] === machine["Machine ID"]);
            return { id: machine["Machine ID"], name: machine["Machine Name"] || legacyProfile?.["Machine Name"] || machine["Machine ID"], machine_type: machine["Machine Type"] || legacyProfile?.["Machine Type"] || "General", availability: machine["Availability status"] || "Available", supported_operations: machineOperations(machine), supported_materials: machine.supportedMaterials || [], operating_cost_per_hour: Number(machine.operatingCostPerHour || 0) };
          }),
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : data.detail?.message || "Scheduling request failed.");
      const reference = Date.parse(data.reference_time);
      if (!Number.isFinite(reference) || !Array.isArray(data.schedule)) throw new Error("The scheduler returned an invalid reference time or schedule.");
      const scheduled = [...data.schedule].sort((a, b) =>
        a.machine.localeCompare(b.machine, undefined, { numeric: true, sensitivity: "base" }) || a.start_minute - b.start_minute
      ).map((row, index) => {
        const job = jobs.find((item) => item["Job ID"] === row.job_id);
        const taskState = job?.Status === "Queued" && reference + row.start_minute * 60_000 > Date.now() ? "Waiting" : job?.Status || "Queued";
        return { Sequence: index + 1, "Job ID": row.job_id, Task: row.task, Machine: row.machine, "Operator ID": row.operator_id, Workforce: `${row.operator} (${row.operator_id})`, Priority: job?.Priority || "—", "Task state": taskState, "Duration (min)": row.end_minute - row.start_minute, "Arrival time": Number.isFinite(row.arrival_minute) ? formatScheduleTime(data.reference_time, row.arrival_minute, true) + " IST" : "—", Due: Number.isFinite(row.due_minute) ? formatScheduleTime(data.reference_time, row.due_minute, true) + " IST" : "—", "Recommended start": formatScheduleTime(data.reference_time, row.start_minute) + " IST", "Recommended end": formatScheduleTime(data.reference_time, row.end_minute) + " IST", "Solver status": row.status || data.status || "—", "Tardiness (min)": row.tardiness_minutes, startMinute: row.start_minute, endMinute: row.end_minute, scheduleReference: data.reference_time };
      });
      setJobs((current) => current.map((job) => { const row = data.schedule.find((item) => item.job_id === job["Job ID"]); return row ? { ...job, Machine: row.machine, Workforce: `${row.operator} (${row.operator_id})` } : activeJobs.some((active) => active["Job ID"] === job["Job ID"]) ? { ...job, Machine: "Unassigned", Workforce: "Unassigned" } : job; }));
      setSchedule(scheduled);
      setSelectedScheduleId(null);
      setSolverSummary({ status: data.status, selectedStatus: data.status, scheduler: data.scheduler, metrics: data.metrics, unscheduledTasks: data.unscheduled_tasks || [], validation: data.validation });
      setRuns((value) => value + 1);
      setLastSchedule(currentTimeDisplayIST());
      const unscheduledCount=data.unscheduled_tasks?.length || 0;
      showNotice(`Schedule status ${data.status}: ${scheduled.length} scheduled, ${unscheduledCount} unscheduled.`);
    } catch (error) { showNotice(error.message || "Could not connect to the scheduling service."); }
    finally { setSolving(false); }
  };

  const addTask = (event) => {
    event.preventDefault();
    const id = taskForm.id.trim() || nextJobId(jobs, archived);
    if (!taskForm.task.trim()) return showNotice("Enter a task name.");
    if ([...jobs, ...archived].some((job) => job["Job ID"].toLowerCase() === id.toLowerCase())) return showNotice("That Job ID is already in use.");
    const arrival = `${taskForm.arrivalDate} ${taskForm.arrivalTime}`;
    const due = `${taskForm.dueDate} ${taskForm.dueTime}`;
    if (istDateTimeValue(due) < istDateTimeValue(arrival)) return showNotice("Due time must be at or after the arrival time.");
    const duration = Number(taskForm.duration) * ({ Minutes: 1, Hours: 60, Days: 1440 }[taskForm.unit]);
    setJobs((current) => [...current, { "Job ID": id, Task: taskForm.task.trim(), Operation: taskForm.operation, Material: taskForm.material.trim(), "Required skills": taskForm.requiredSkills, Dependencies: taskForm.dependencies, "Allow late": taskForm.allowLate, Machine: "Unassigned", Priority: taskForm.priority, "Duration (min)": duration, Arrival: arrival, Due: due, Status: "Queued", Progress: 0, Workforce: "Unassigned" }]);
    setTaskForm(newTaskForm());
    setDueManuallySet(false);
    showNotice(`${id} added to the queue.`);
  };

  const completeTask = (jobId = selectedJob) => {
    if (!jobId) return;
    const job = jobs.find((item) => item["Job ID"] === jobId);
    if (!job) return;
    setArchived((current) => [...current, { ...job, Status: "Completed", Progress: 100, "Completed at": new Date().toISOString() }]);
    setJobs((current) => current.filter((item) => item["Job ID"] !== jobId));
    setSelectedJob("");
    showNotice(`${jobId} completed and archived.`);
  };

  const addOperator = async (event) => {
    event.preventDefault();
    const id = operatorForm.id.trim();
    const name = operatorForm.name.trim();
    if (!id || !name) return showNotice("Enter an operator ID and name.");
    if (operators.some((row) => row["Operator ID"].toLowerCase() === id.toLowerCase())) return showNotice("That operator ID is already in use.");
    if (operators.some((row) => row.Operator.toLowerCase() === name.toLowerCase())) return showNotice("An operator with that name already exists.");
    if (!operatorForm.skills.length) return showNotice("Select at least one operator skill.");
    const newOperator = { "Operator ID": id, Operator: name, Skills: operatorForm.skills, Availability: operatorForm.availability, Certifications: operatorForm.certifications, "Assigned jobs": 0, Utilization: 0 };
    if (!await persistResource("operators", id, name, newOperator, "POST")) return;
    setOperators((current) => [...current, newOperator]);
    setSchedule(null);
    setSolverSummary(null);
    setOperatorForm({ id: "", name: "", skills: [OPERATIONS[0]], certifications: [], availability: "Available" });
    showNotice(`${name} added to the workforce.`);
  };

  const addMachine = async (event) => {
    event.preventDefault();
    const id = machineForm.id.trim();
    const name = machineForm.name.trim();
    const type = machineForm.type.trim();
    if (!id || !name || !type) return showNotice("Enter the machine ID, name, and type.");
    if (machines.some((machine) => machine["Machine ID"].toLowerCase() === id.toLowerCase())) return showNotice("That machine ID is already in use.");
    if (!machineForm.supportedOperations.length) return showNotice("Select at least one supported operation.");
    const newMachine = { "Machine ID": id, "Machine Name": name, "Machine Type": type, "Availability status": machineForm.availability, "Supported operations": machineForm.supportedOperations, supportedMaterials: machineForm.supportedMaterials, operatingCostPerHour: Number(machineForm.operatingCostPerHour || 0) };
    if (!await persistResource("machines", id, name, newMachine, "POST")) return;
    setMachines((current) => [...current, newMachine]);
    setSchedule(null);
    setSolverSummary(null);
    setMachineForm({ id: "", name: "", type: "", availability: "Available", supportedOperations: [OPERATIONS[0]], supportedMaterials: [], operatingCostPerHour: 0 });
    showNotice(`${id} added as a machine resource.`);
  };

  const deleteMachine = (machineId) => {
    const machine = machines.find((item) => item["Machine ID"] === machineId);
    if (machine) { void fetch(`/api/resources/machines/${encodeURIComponent(machineId)}/deactivate`, { method: "PATCH" }).catch(() => {}); }
    const wasScheduled = schedule?.some((row) => row.Machine === machineId);
    setMachines((current) => current.map((item) => item["Machine ID"] === machineId ? { ...item, "Availability status": "Offline" } : item));
    setJobs((current) => current.map((job) => (job.Machine === machineId || schedule?.some((row) => row["Job ID"] === job["Job ID"] && row.Machine === machineId))
      ? { ...job, Machine: "Unassigned", Workforce: "Unassigned" }
      : job));
    setSchedule(null);
    setSolverSummary(null);
    showNotice(wasScheduled ? `${machineId} removed. The saved schedule was cleared.` : `${machineId} removed from machine resources.`);
  };

  const updateMachine = (machineId, field, value) => {
    setMachines((current) => current.map((machine) => {
      if (machine["Machine ID"] !== machineId) return machine;
      const updated={ ...machine, [field]: value };
      void persistResource("machines", machineId, updated["Machine Name"] || machineId, updated);
      return updated;
    }));
    setSchedule(null);
    setSolverSummary(null);
  };

  const updateOperator = (operatorId, field, value) => {
    setOperators((current) => current.map((operator) => {
      if (operator["Operator ID"] !== operatorId) return operator;
      const updated={ ...operator, [field]: value };
      void persistResource("operators", operatorId, updated.Operator || operatorId, updated);
      return updated;
    }));
    setSchedule(null);
    setSolverSummary(null);
  };

  const deleteOperator = (operatorId) => {
    const operator = operators.find((row) => row["Operator ID"] === operatorId);
    if (!operator) return;
    const wasScheduled = schedule?.some((row) => row.Workforce?.endsWith(`(${operatorId})`));
    void fetch(`/api/resources/operators/${encodeURIComponent(operatorId)}/deactivate`, { method: "PATCH" }).catch(() => {});
    setOperators((current) => current.map((row) => row["Operator ID"] === operatorId ? { ...row, Availability: "Off shift" } : row));
    setJobs((current) => current.map((job) => job.Workforce?.endsWith(`(${operatorId})`) ? { ...job, Workforce: "Unassigned" } : job));
    setSchedule(null);
    setSolverSummary(null);
    showNotice(wasScheduled ? `${operator.Operator} removed. The saved schedule was cleared.` : `${operator.Operator} removed from the workforce.`);
  };

  const updateJob = (jobId, field, value) => {
    setJobs((current) => current.map((job) => job["Job ID"] === jobId ? { ...job, [field]: field === "Duration (min)" || field === "Progress" ? Number(value) : value } : job));
    if (["Operation", "Priority", "Duration (min)", "Arrival", "Due", "Material", "Required skills", "Dependencies", "Allow late"].includes(field)) {
      setSchedule(null);
      setSolverSummary(null);
    }
  };

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">DynamiQ</div>
          <nav aria-label="Main navigation">
            {PAGES.map((item) => <button className={`nav-link ${page === item ? "active" : ""}`} key={item} onClick={() => setPage(item)}>{item}</button>)}
          </nav>
        </div>
      </header>

      <main className="app-shell">
        <div className="page-heading">
          <div><h2>{page}</h2><p className="small-muted">Manufacturing intelligence / real-time operations workspace</p></div>
          <div className="live-date">● Live demo <span>·</span> {new Date().toLocaleDateString("en-GB", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric" })} IST</div>
        </div>
        {databaseError && <div className="info-box" role="alert">MongoDB connection failed: {databaseError}. Check backend/.env and make sure the MongoDB server is running.</div>}
        {noticeMessage && <div className="toast" role="status">{noticeMessage}</div>}

        {page === "Overview" && <>
          <section className="hero"><div className="hero-pill">✦ OR-TOOLS CP-SAT · DYNAMIC SCHEDULING</div><h1>Make every machine minute count.</h1><p>Monitor production, prioritize tasks, and generate optimized schedules from one workspace.</p></section>
          <div className="metric-grid three"><Metric label="Active jobs" value={running} foot="Current active tasks" icon="◉"/><Metric label="Queued tasks" value={queued} foot="Awaiting machine allocation" icon="↗"/><Metric label="Completed today" value={archived.length} foot="Completed tasks in this browser" icon="✓"/></div>
          <section className="section"><h3 className="section-title">Live job queue</h3>
          {schedule?.length ? <DataTable columns={completionColumns} rows={schedule}/> : activeJobs.length ? <DataTable columns={["Job ID", "Assigned Operator", "Task", "Machine", "Priority", "Arrival (IST)", "Due (IST)", "Status", "Progress"]}><>{activeJobs.map((job) => <tr key={job["Job ID"]}><td>{job["Job ID"]}</td><td>{job.Workforce}</td><td>{job.Task}</td><td>{job.Machine}</td><td>{job.Priority}</td><td>{job.Arrival || "—"}</td><td>{job.Due}</td><td><StatusBadge status={job.Status}/></td><td>{job.Progress}%</td></tr>)}</></DataTable> : <div className="info-box">No active jobs in the live queue.</div>}
          </section>
          <section className="section"><h3 className="section-title">Schedule Gantt chart</h3>{schedule?.length ? <AccurateGanttChart rows={schedule} referenceTime={schedule[0]?.scheduleReference} schedulerName={solverSummary?.scheduler} solverStatus={solverSummary?.selectedStatus} selectedId={selectedScheduleId} onSelect={setSelectedScheduleId} zoom={ganttZoom} onZoomChange={setGanttZoom}/> : <div className="info-box">{solverSummary ? `No tasks were scheduled (${solverSummary.selectedStatus}). Review the diagnostics in Task Scheduling.` : "Generate a schedule in Task Scheduling to view the machine timeline here."}</div>}</section>
          <p className="caption">Illustrative dashboard data. Generate a schedule in Task Scheduling to assign available operators and machines.</p>
        </>}

        {page === "Task Scheduling" && <>
          <p className="intro-copy">Generate a schedule with CP-SAT, FCFS, SJF, or priority dispatching. Machines are selected from Workforce resources.</p>
          <div className="form-grid three"><Field label="Scheduling algorithm"><select value={scheduler} onChange={(event) => { setScheduler(event.target.value); if (event.target.value !== "cp_sat") setAllowUnscheduled(false); }}><option value="cp_sat">CP-SAT</option><option value="fcfs">First come, first served (FCFS)</option><option value="sjf">Shortest job first (SJF)</option><option value="priority">Priority</option></select></Field><Field label="Optimization objective"><select disabled={scheduler !== "cp_sat"} value={objective} onChange={(event) => setObjective(event.target.value)}><option value="balanced">Balanced (makespan + due dates)</option><option value="makespan">Minimize makespan</option><option value="tardiness">Minimize weighted tardiness</option><option value="workload">Balance operator workload</option><option value="cost">Minimize machine operating cost</option></select></Field><Field label="Priority rule"><select disabled={scheduler !== "cp_sat"} value={priorityPolicy} onChange={(event) => setPriorityPolicy(event.target.value)}><option value="preference">Priority as preference</option><option value="strict">Strict machine queue order</option></select></Field></div>
          <div className="constraint-grid"><label><input type="checkbox" disabled={scheduler !== "cp_sat"} checked={allowUnscheduled} onChange={(event) => setAllowUnscheduled(event.target.checked)}/>Allow unscheduled tasks and report why</label>{allowUnscheduled && <Field label="Unscheduled task penalty"><input type="number" min="1" value={unscheduledPenalty} onChange={(event) => setUnscheduledPenalty(event.target.value)}/></Field>}</div>
          <p className="caption">Machine/operator eligibility, task dependencies, priority, and due dates are sent to the scheduler. Processing uses each task’s entered duration. Due dates are soft by default. Priority affects the solver objective unless strict queue order is selected. All displayed timestamps are IST.</p>
          <button className="primary-action" onClick={makeSchedule} disabled={solving}>{solving ? "Scheduling…" : "Generate schedule"}</button>
          {solverSummary && <section className="section schedule-section"><p className="caption">Generated by {solverSummary.scheduler} · Status: {solverSummary.selectedStatus} · Run #{runs} at {lastSchedule}.</p><div className="metric-grid three schedule-summary-metrics"><Metric label="Makespan" value={`${solverSummary.metrics?.makespan || 0} min`} foot="From schedule reference" icon="◷"/><Metric label="Scheduled tasks" value={solverSummary.metrics?.scheduled_task_count ?? schedule?.length ?? 0} foot={`${solverSummary.metrics?.unscheduled_task_count || 0} unscheduled`} icon="✓"/><Metric label="On-time completion" value={`${solverSummary.metrics?.deadline_performance_percent ?? 0}%`} foot={`${solverSummary.metrics?.late_task_count || 0} late tasks`} icon="⌁"/><Metric label="Operating cost" value={`${solverSummary.metrics?.estimated_operating_cost ?? 0}`} foot="Selected machine alternatives" icon="$"/></div><h3 className="section-title">{solverSummary.scheduler} detailed schedule</h3>{schedule?.length ? <DataTable columns={scheduleColumns}><>{schedule.map((row) => <tr key={row["Job ID"]} className={selectedScheduleId === row["Job ID"] ? "schedule-row-selected" : "schedule-row"} onClick={() => setSelectedScheduleId(selectedScheduleId === row["Job ID"] ? null : row["Job ID"])}><td>{row.Sequence}</td><td><button type="button" className="table-select-button" aria-pressed={selectedScheduleId === row["Job ID"]}>{row["Job ID"]}</button></td><td>{row.Task}</td><td>{row.Machine}</td><td>{row.Workforce}</td><td>{row.Priority}</td><td>{row["Arrival time"]}</td><td>{row["Recommended start"]}</td><td>{row["Recommended end"]}</td><td>{row["Duration (min)"]}</td><td>{row.Due}</td><td>{row["Tardiness (min)"] ?? "—"}</td><td>{row["Solver status"] ?? "—"}</td></tr>)}</></DataTable> : <div className="info-box">No feasible tasks were scheduled. Review solver status and unscheduled-task diagnostics below.</div>}<h3 className="section-title gantt-title">Schedule Gantt chart</h3>{schedule?.length > 0 && <AccurateGanttChart rows={schedule} referenceTime={schedule[0]?.scheduleReference} schedulerName={solverSummary?.scheduler} solverStatus={solverSummary?.selectedStatus} selectedId={selectedScheduleId} onSelect={setSelectedScheduleId} zoom={ganttZoom} onZoomChange={setGanttZoom}/>}<h3 className="section-title">Machine utilization</h3><DataTable columns={["Machine", "Utilization"]}>{Object.entries(solverSummary.metrics?.resource_utilization || {}).map(([resource, percent]) => <tr key={resource}><td>{resource}</td><td>{(percent*100).toFixed(1)}%</td></tr>)}</DataTable><h3 className="section-title">Operator utilization</h3><DataTable columns={["Operator", "Utilization"]}>{Object.entries(solverSummary.metrics?.operator_utilization || {}).map(([resource, percent]) => <tr key={resource}><td>{resource}</td><td>{(percent*100).toFixed(1)}%</td></tr>)}</DataTable>{solverSummary.unscheduledTasks?.length > 0 && <><h3 className="section-title">Unscheduled tasks and diagnostics</h3><DataTable columns={["Task ID", "Reason"]}>{solverSummary.unscheduledTasks.map((item) => <tr key={item.job_id}><td>{item.job_id}</td><td>{item.reason}</td></tr>)}</DataTable></>}<div className="table-actions"><span className="caption">Independent validation: {solverSummary.validation?.valid ? "valid" : "invalid"} · Schedule generated at {lastSchedule}</span></div></section>}
        </>}

        {page === "Task Management" && <>
          <p className="intro-copy">Track work orders and add jobs to the live demo queue.</p>
          <details className="details-card"><summary>＋ Add a job</summary><form className="form-grid three add-form" onSubmit={addTask}>
            <Field label="Job ID"><input value={taskForm.id} placeholder={nextJobId(jobs, archived)} onChange={(event) => setTaskForm({ ...taskForm, id: event.target.value })}/></Field>
            <Field label="Task name"><input required value={taskForm.task} onChange={(event) => setTaskForm({ ...taskForm, task: event.target.value })}/></Field>
            <Field label="Required operation"><input required placeholder="e.g. CNC machining, Welding" value={taskForm.operation} onChange={(event) => setTaskForm({ ...taskForm, operation: event.target.value })}/></Field>
            <Field label="Priority"><select value={taskForm.priority} onChange={(event) => setTaskForm({ ...taskForm, priority: event.target.value })}>{["Low", "Medium", "High", "Critical"].map((value) => <option key={value}>{value}</option>)}</select></Field>
            <Field label="Duration"><div className="inline-fields"><input type="number" min="1" max="365" value={taskForm.duration} onChange={(event) => setTaskForm({ ...taskForm, duration: event.target.value })}/><select value={taskForm.unit} onChange={(event) => setTaskForm({ ...taskForm, unit: event.target.value })}><option>Minutes</option><option>Hours</option><option>Days</option></select></div></Field>
            <Field label="Arrival date and time (IST)"><div className="inline-fields"><input required type="date" value={taskForm.arrivalDate} onChange={(event) => updateArrivalTime("arrivalDate", event.target.value)}/><input required type="time" value={taskForm.arrivalTime} onChange={(event) => updateArrivalTime("arrivalTime", event.target.value)}/></div></Field>
            <Field label="Due date and time (IST)"><div className="inline-fields"><input required type="date" value={taskForm.dueDate} onChange={(event) => { setDueManuallySet(true); setTaskForm({ ...taskForm, dueDate: event.target.value }); }}/><input required type="time" value={taskForm.dueTime} onChange={(event) => { setDueManuallySet(true); setTaskForm({ ...taskForm, dueTime: event.target.value }); }}/></div></Field>
            <Field label="Required material (optional)"><input value={taskForm.material} placeholder="e.g. Aluminum" onChange={(event) => setTaskForm({ ...taskForm, material: event.target.value })}/></Field>
            <Field label="Required operator skills"><TagInput value={taskForm.requiredSkills} placeholder="Type a required certification or skill" onChange={(requiredSkills) => setTaskForm({ ...taskForm, requiredSkills })}/></Field>
            <Field label="Predecessor tasks"><select multiple value={taskForm.dependencies} onChange={(event) => setTaskForm({ ...taskForm, dependencies: [...event.target.selectedOptions].map((option) => option.value) })}>{activeJobs.filter((job) => job["Job ID"] !== (taskForm.id || nextJobId(jobs, archived))).map((job) => <option key={job["Job ID"]} value={job["Job ID"]}>{job["Job ID"]} · {job.Task}</option>)}</select></Field>
            <label className="checkbox-field"><input type="checkbox" checked={taskForm.allowLate} onChange={(event) => setTaskForm({ ...taskForm, allowLate: event.target.checked })}/>Allow this task to finish after its due time (late completion is penalized)</label>
            <p className="caption due-time-hint">{dueManuallySet ? "Manual due time selected. Change the due fields directly; arrival changes will preserve this due time." : "Due time defaults to 2 hours after arrival. You can adjust the due date or time manually."}</p>
            <div className="form-submit"><button className="primary-action compact" type="submit">Add job</button></div>
          </form></details>
          <section className="section"><h3 className="section-title">Work orders</h3>{activeJobs.length ? <><p className="caption">Machine assignments come from compatible available Workforce resources. Arrival and due timestamps are IST.</p><DataTable columns={["Job ID", "Task", "Required operation", "Material", "Required skills", "Predecessors", "Allow late", "Machine", "Priority", "Duration (min)", "Arrival (IST)", "Due (IST)", "Status", "Progress", "Workforce"]}><>{activeJobs.map((job) => <tr key={job["Job ID"]}>
            <td><input aria-label="Job ID" value={job["Job ID"]} onChange={(event) => updateJob(job["Job ID"], "Job ID", event.target.value)} disabled/></td>
            <td><input aria-label="Task" value={job.Task} onChange={(event) => updateJob(job["Job ID"], "Task", event.target.value)}/></td>
            <td><input aria-label="Required operation" value={job.Operation || inferOperation(job.Task)} onChange={(event) => updateJob(job["Job ID"], "Operation", event.target.value)}/></td>
            <td><input aria-label={`Material for ${job["Job ID"]}`} value={job.Material || ""} onChange={(event) => updateJob(job["Job ID"], "Material", event.target.value)}/></td>
            <td><TagInput value={job["Required skills"] || []} placeholder="Add skill" onChange={(value) => updateJob(job["Job ID"], "Required skills", value)}/></td>
            <td><select aria-label={`Predecessors for ${job["Job ID"]}`} multiple value={job.Dependencies || []} onChange={(event) => updateJob(job["Job ID"], "Dependencies", [...event.target.selectedOptions].map((option) => option.value))}>{activeJobs.filter((item) => item["Job ID"] !== job["Job ID"]).map((item) => <option key={item["Job ID"]} value={item["Job ID"]}>{item["Job ID"]}</option>)}</select></td>
            <td><input aria-label={`Allow late completion for ${job["Job ID"]}`} type="checkbox" checked={job["Allow late"] !== false} onChange={(event) => updateJob(job["Job ID"], "Allow late", event.target.checked)}/></td>
            <td>{job.Machine || "Unassigned"}</td>
            <td><select aria-label="Priority" value={job.Priority} onChange={(event) => updateJob(job["Job ID"], "Priority", event.target.value)}>{["Low", "Medium", "High", "Critical"].map((value) => <option key={value}>{value}</option>)}</select></td>
            <td><input aria-label="Duration" type="number" min="1" value={job["Duration (min)"]} onChange={(event) => updateJob(job["Job ID"], "Duration (min)", event.target.value)}/></td>
            <td><input aria-label="Arrival (IST)" type="datetime-local" value={(job.Arrival || "").replace(" ", "T")} onChange={(event) => updateJob(job["Job ID"], "Arrival", event.target.value.replace("T", " "))}/></td>
            <td><input aria-label="Due (IST)" type="datetime-local" value={(job.Due || "").replace(" ", "T")} onChange={(event) => updateJob(job["Job ID"], "Due", event.target.value.replace("T", " "))}/></td>
            <td><StatusBadge status={job.Status}/></td><td><input aria-label="Progress" type="number" min="0" max="100" value={job.Progress} onChange={(event) => updateJob(job["Job ID"], "Progress", event.target.value)}/></td>
            <td><input aria-label="Workforce" value={job.Workforce} onChange={(event) => updateJob(job["Job ID"], "Workforce", event.target.value)}/></td>
          </tr>)}</></DataTable></> : <div className="info-box">No pending tasks. Completed tasks are archived in this browser.</div>}</section>
          <section className="section completion-panel"><h3 className="section-title">Complete a task</h3>{activeJobs.length ? <div className="complete-row"><select value={selectedJob || activeJobs[0]["Job ID"]} onChange={(event) => setSelectedJob(event.target.value)}>{activeJobs.map((job) => <option key={job["Job ID"]}>{job["Job ID"]}</option>)}</select><button className="primary-action compact" onClick={() => completeTask(selectedJob || activeJobs[0]["Job ID"])}>Mark task completed</button></div> : <div className="info-box">All tasks are completed and archived in this browser.</div>}</section>
          <button className="secondary-action" onClick={() => downloadCsv(jobs, "jobs.csv")}>Export jobs CSV</button>
        </>}

        {page === "Workforce" && <>
          <p className="intro-copy">Add machine capabilities and operator skills. Scheduling considers only resources that are available and qualified for each task operation.</p>
          <p className="caption">Machine type can further limit supported operations. Use a multi-purpose type when the machine is configured for unrelated operation families.</p>
          <section className="section"><h3 className="section-title">Machine resources</h3><details className="details-card"><summary>Add a machine resource</summary><form className="form-grid three add-form" onSubmit={addMachine}>
            <Field label="Machine ID"><input required value={machineForm.id} onChange={(event) => setMachineForm({ ...machineForm, id: event.target.value })}/></Field>
            <Field label="Machine name"><input required value={machineForm.name} onChange={(event) => setMachineForm({ ...machineForm, name: event.target.value })}/></Field>
            <Field label="Machine type"><input required value={machineForm.type} onChange={(event) => setMachineForm({ ...machineForm, type: event.target.value })}/></Field>
            <Field label="Availability status"><select value={machineForm.availability} onChange={(event) => setMachineForm({ ...machineForm, availability: event.target.value })}>{MACHINE_AVAILABILITY.map((value) => <option key={value}>{value}</option>)}</select></Field>
            <Field label="Supported operations"><TagInput value={machineForm.supportedOperations} placeholder="Type an operation" onChange={(supportedOperations) => setMachineForm({ ...machineForm, supportedOperations })}/></Field>
            <Field label="Supported materials"><TagInput value={machineForm.supportedMaterials} placeholder="Type a material" onChange={(supportedMaterials) => setMachineForm({ ...machineForm, supportedMaterials })}/></Field>
            <Field label="Operating cost per hour"><input type="number" min="0" step="0.01" value={machineForm.operatingCostPerHour} onChange={(event) => setMachineForm({ ...machineForm, operatingCostPerHour: event.target.value })}/></Field>
            <div className="form-submit"><button className="primary-action compact" type="submit">Add machine</button></div>
          </form></details>
          <DataTable columns={["Machine ID", "Machine name", "Machine type", "Availability status", "Supported operations", "Materials", "Cost/hour", "Actions"]}>{machines.length ? machines.map((machine) => <tr key={machine["Machine ID"]}>
            <td>{machine["Machine ID"]}</td>
            <td><input aria-label={`Machine name for ${machine["Machine ID"]}`} value={machine["Machine Name"] || STARTER_MACHINES.find((item) => item["Machine ID"] === machine["Machine ID"])?.["Machine Name"] || machine["Machine ID"]} onChange={(event) => updateMachine(machine["Machine ID"], "Machine Name", event.target.value)}/></td>
            <td><input aria-label={`Machine type for ${machine["Machine ID"]}`} value={machine["Machine Type"] || STARTER_MACHINES.find((item) => item["Machine ID"] === machine["Machine ID"])?.["Machine Type"] || "General"} onChange={(event) => updateMachine(machine["Machine ID"], "Machine Type", event.target.value)}/></td>
            <td><select aria-label={`Availability for ${machine["Machine ID"]}`} value={machine["Availability status"] || "Available"} onChange={(event) => updateMachine(machine["Machine ID"], "Availability status", event.target.value)}>{MACHINE_AVAILABILITY.map((value) => <option key={value}>{value}</option>)}</select></td>
            <td><TagInput value={machineOperations(machine)} placeholder="Add operation" onChange={(supportedOperations) => updateMachine(machine["Machine ID"], "Supported operations", supportedOperations)}/></td>
            <td><TagInput value={machine.supportedMaterials || []} placeholder="Add material" onChange={(supportedMaterials) => updateMachine(machine["Machine ID"], "supportedMaterials", supportedMaterials)}/></td>
            <td><input aria-label={`Cost per hour for ${machine["Machine ID"]}`} type="number" min="0" step="0.01" value={machine.operatingCostPerHour || 0} onChange={(event) => updateMachine(machine["Machine ID"], "operatingCostPerHour", Number(event.target.value))}/></td>
            <td><button type="button" className="delete-action" aria-label={`Deactivate machine ${machine["Machine ID"]}`} onClick={() => deleteMachine(machine["Machine ID"])}>Deactivate</button></td>
          </tr>) : <tr><td colSpan="8">No machines added yet. Add at least one machine before scheduling.</td></tr>}</DataTable></section>
          <details className="details-card"><summary>Add an operator</summary><form className="form-grid three add-form" onSubmit={addOperator}>
            <Field label="Operator ID"><input required value={operatorForm.id} onChange={(event) => setOperatorForm({ ...operatorForm, id: event.target.value })}/></Field>
            <Field label="Operator name"><input required value={operatorForm.name} onChange={(event) => setOperatorForm({ ...operatorForm, name: event.target.value })}/></Field>
            <Field label="Skills"><TagInput value={operatorForm.skills} placeholder="Type a skill" onChange={(skills) => setOperatorForm({ ...operatorForm, skills })}/></Field>
            <Field label="Certifications"><TagInput value={operatorForm.certifications} placeholder="Type a certification" onChange={(certifications) => setOperatorForm({ ...operatorForm, certifications })}/></Field>
            <Field label="Availability"><select value={operatorForm.availability} onChange={(event) => setOperatorForm({ ...operatorForm, availability: event.target.value })}>{OPERATOR_AVAILABILITY.map((value) => <option key={value}>{value}</option>)}</select></Field>
            <div className="form-submit"><button className="primary-action compact" type="submit">Add operator</button></div>
          </form></details>
          <div className="metric-grid three workforce-metrics"><Metric label="Active operators" value={operators.length} foot="Listed in workforce" icon="♙"/><Metric label="Available now" value={operators.filter((operator) => operator.Availability === "Available").length} foot="Ready for assignment" icon="✓"/><Metric label="Avg. utilization" value={`${Math.round(operators.length ? operators.reduce((sum, operator) => sum + Number(operator.Utilization), 0) / operators.length : 0)}%`} foot="Across listed operators" icon="◷"/></div>
          <section className="section"><DataTable columns={["Operator ID", "Operator name", "Availability", "Skills", "Certifications", "Assigned jobs", "Actions"]}>{operators.length ? operators.map((operator) => <tr key={operator["Operator ID"]}><td>{operator["Operator ID"]}</td><td><input aria-label={`Name for ${operator["Operator ID"]}`} value={operator.Operator} onChange={(event) => updateOperator(operator["Operator ID"], "Operator", event.target.value)}/></td><td><select aria-label={`Availability for ${operator.Operator}`} value={operator.Availability} onChange={(event) => updateOperator(operator["Operator ID"], "Availability", event.target.value)}>{OPERATOR_AVAILABILITY.map((value) => <option key={value}>{value}</option>)}</select></td><td><TagInput value={operatorSkills(operator)} placeholder="Add skill" onChange={(skills) => updateOperator(operator["Operator ID"], "Skills", skills)}/></td><td><TagInput value={operator.Certifications || []} placeholder="Add certification" onChange={(certifications) => updateOperator(operator["Operator ID"], "Certifications", certifications)}/></td><td>{operator["Assigned jobs"] || 0}</td><td><button type="button" className="delete-action" aria-label={`Deactivate ${operator.Operator}`} onClick={() => deleteOperator(operator["Operator ID"])}>Deactivate</button></td></tr>) : <tr><td colSpan="7">No operators added yet.</td></tr>}</DataTable></section>
        </>}

        <footer>DynamiQ · OR-Tools CP-SAT Dynamic Scheduling · Prototype dashboard</footer>
      </main>
    </>
  );
}

function Field({ label, children }) { return <label className="field"><span>{label}</span>{children}</label>; }
function StatusBadge({ status }) { return <span className={`status status-${status.toLowerCase()}`}>{status}</span>; }
function nextJobId(jobs, archived) {
  const ids = new Set([...jobs, ...archived].map((job) => job["Job ID"]));
  let candidate = 1048;
  while (ids.has(`JOB-${candidate}`)) candidate += 1;
  return `JOB-${candidate}`;
}
