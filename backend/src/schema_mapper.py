"""Map dataset columns to the solver's internal schema."""
from dataclasses import dataclass, field

@dataclass(frozen=True)
class SchemaMapping:
    tasks: dict[str, str] = field(default_factory=lambda: {
        "task_id": "Task_ID", "duration": "Task_Duration_Min", "arrival": "Arrival_Time_Min",
        "due": "Due_Date_Min", "priority": "Priority", "original_operator": "Original_Operator_ID",
        "original_resource": "Original_Resource_ID"})
    eligibility: dict[str, str] = field(default_factory=lambda: {
        "task_id": "Task_ID", "operator": "Operator_ID", "resource": "Resource_ID",
        "process_time": "Process_Time_Min"})
    def rename(self, tasks, eligibility):
        return (tasks.rename(columns={v:k for k,v in self.tasks.items()}),
                eligibility.rename(columns={v:k for k,v in self.eligibility.items()}))
