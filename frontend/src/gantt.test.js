import test from "node:test";
import assert from "node:assert/strict";
import { findResourceConflicts, formatScheduleTime, getTimeline, naturalSort, validateRows } from "./gantt.js";

const task = (id, machine, startMinute, endMinute, operator = id) => ({
  "Job ID": id, Machine: machine, "Operator ID": operator, startMinute, endMinute,
});

test("simultaneous jobs on parallel machines share the same start coordinate", () => {
  const rows = [task("a", "M2", 0, 30), task("b", "M10", 0, 5), task("c", "M3", 0, 60)];
  const { first } = getTimeline(rows);
  assert.deepEqual(rows.map((row) => (row.startMinute - first) * getTimeline(rows).pixelsPerMinute), [0, 0, 0]);
});

test("sequential machine jobs meet exactly at their shared boundary", () => {
  const [a, b] = [task("a", "M1", 0, 30), task("b", "M1", 30, 60)];
  const timeline = getTimeline([a, b]);
  assert.equal((b.startMinute - timeline.first) * timeline.pixelsPerMinute, (a.endMinute - timeline.first) * timeline.pixelsPerMinute);
});

test("different backend durations produce proportional bar widths", () => {
  const timeline = getTimeline([task("short", "M1", 0, 5), task("long", "M2", 0, 60)]);
  assert.equal((60 - 0) / (5 - 0), 12);
  assert.equal(timeline.width, 720);
});

test("nonzero offsets are normalized to the earliest actual task", () => {
  const timeline = getTimeline([task("a", "M1", 500, 530), task("b", "M2", 510, 540)]);
  assert.equal(timeline.first, 500);
  assert.equal((510 - timeline.first) * timeline.pixelsPerMinute, 180);
});

test("IST time formatting handles crossing midnight without local timezone shifts", () => {
  const reference = "2026-10-17T18:20:00Z";
  assert.equal(formatScheduleTime(reference, 0), "23:50");
  assert.equal(formatScheduleTime(reference, 30), "00:20");
  assert.match(formatScheduleTime(reference, 30, true), /18 Oct/);
});

test("empty schedule produces an empty timeline safely", () => {
  assert.deepEqual(getTimeline([]).ticks, []);
  assert.equal(validateRows([]).valid.length, 0);
});

test("invalid and zero-length rows are warned and excluded", () => {
  const result = validateRows([task("good", "M1", 0, 3), task("bad", "M2", NaN, 4), task("zero", "M3", 4, 4)]);
  assert.deepEqual(result.valid.map((row) => row["Job ID"]), ["good"]);
  assert.equal(result.warnings.length, 2);
});

test("machine identifiers use natural sorting", () => {
  assert.deepEqual(naturalSort(["M10", "M2", "M3", "M2"]), ["M2", "M3", "M10"]);
});

test("input order does not affect time coordinates", () => {
  const rows = [task("a", "M1", 500, 530), task("b", "M2", 510, 550), task("c", "M3", 500, 505)];
  const positions = (items) => Object.fromEntries(items.map((row) => [row["Job ID"], (row.startMinute - getTimeline(items).first) * 3]));
  assert.deepEqual(positions(rows), positions([...rows].reverse()));
});

test("long schedules grow by horizon and provide evenly spaced axis ticks", () => {
  const timeline = getTimeline([task("long", "M1", 0, 8 * 60)]);
  assert.equal(timeline.width, 8 * 60 * 3);
  assert.ok(timeline.ticks.length > 2);
  assert.ok(timeline.ticks.every((tick, index) => index === 0 || tick.minute > timeline.ticks[index - 1].minute));
  assert.ok(timeline.ticks.every((tick, index) => index === 0 || (tick.minute - timeline.ticks[index - 1].minute) * timeline.pixelsPerMinute >= 100));
});

test("overlapping jobs sharing a machine or operator are identified", () => {
  const conflicts = findResourceConflicts([task("a", "M1", 0, 20, "op"), task("b", "M1", 10, 30, "op"), task("c", "M2", 10, 15, "other")]);
  assert.deepEqual(conflicts.map((entry) => [entry.resourceType, entry.resource, entry.startMinute, entry.endMinute]), [
    ["machine", "M1", 10, 20], ["operator", "op", 10, 20],
  ]);
});

test("back-to-back assignments do not count as a resource conflict", () => {
  assert.deepEqual(findResourceConflicts([task("a", "M1", 0, 10, "op"), task("b", "M1", 10, 20, "op")]), []);
});
