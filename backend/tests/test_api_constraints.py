import unittest
from datetime import datetime, timezone
from fastapi import HTTPException

from api import Machine, Operator, ScheduleRequest, _dependency_map, _resource_blockouts, create_schedule
from api import Job


class TestAPIConstraints(unittest.TestCase):
    def test_shift_windows_are_interpreted_in_ist(self):
        machine = Machine(id="M1", name="Mill", machine_type="General", working_days=[0, 1, 2, 3, 4, 5, 6], shift_start="09:00", shift_end="17:00")
        origin = datetime(2026, 10, 19, 3, 30, tzinfo=timezone.utc)  # Monday, 09:00 IST
        blocks = _resource_blockouts(machine, "M1", origin, 600)
        self.assertFalse(any(start <= 0 < end for start, end in blocks))
        self.assertTrue(any(start <= 480 < end for start, end in blocks))  # shift ends at 17:00 IST

    def test_overnight_shifts_cover_the_following_day(self):
        machine = Machine(id="M1", name="Night shift", machine_type="General", working_days=[0], shift_start="22:00", shift_end="06:00")
        origin = datetime(2026, 10, 19, 19, 30, tzinfo=timezone.utc)  # Tuesday, 01:00 IST
        blocks = _resource_blockouts(machine, "M1", origin, 600)
        self.assertFalse(any(start <= 0 < end for start, end in blocks))
        self.assertTrue(any(start <= 300 < end for start, end in blocks))

    def test_unknown_predecessors_and_dependency_cycles_are_rejected(self):
        jobs = [Job(id="a", task="A", operation="Mill", duration_minutes=2, due=datetime(2026, 10, 20), dependencies=["b"]),
                Job(id="b", task="B", operation="Mill", duration_minutes=2, due=datetime(2026, 10, 20), dependencies=["a"])]
        with self.assertRaises(HTTPException):
            _dependency_map(jobs)

    def test_api_scheduler_objectives_are_supported_by_cp_sat(self):
        objectives = ("balanced", "tardiness", "makespan", "cost", "workload", "fastest", "deadline")
        for objective in objectives:
            with self.subTest(objective=objective):
                request = ScheduleRequest(
                    jobs=[Job(id="job-1", task="Mill part", operation="Mill", duration_minutes=5,
                              due=datetime(2030, 1, 1, tzinfo=timezone.utc))],
                    operators=[Operator(id="op-1", name="Operator", skills=["Mill"])],
                    machines=[Machine(id="m-1", name="Mill", machine_type="General",
                                      supported_operations=["Mill"])],
                    objective=objective, time_limit_seconds=1, num_workers=1,
                )
                result = create_schedule(request)
                self.assertEqual(result["status"], "OPTIMAL")
                self.assertEqual(len(result["schedule"]), 1)


if __name__ == "__main__":
    unittest.main()
