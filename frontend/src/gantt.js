export const MACHINE_COLUMN_WIDTH = 120;
export const PIXELS_PER_MINUTE = 3;
export const MIN_TIMELINE_WIDTH = 720;

export function validateRows(rows = []) {
  const valid = [];
  const warnings = [];
  rows.forEach((row, index) => {
    const asMinute = (value) => typeof value === "number" ? value : typeof value === "string" && value.trim() ? Number(value) : NaN;
    const start = asMinute(row.startMinute);
    const end = asMinute(row.endMinute);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
      warnings.push(`${row["Job ID"] || `Schedule row ${index + 1}`} has invalid start or end time.`);
      return;
    }
    valid.push({ ...row, startMinute: start, endMinute: end });
  });
  return { valid, warnings };
}

export function naturalSort(values) {
  return [...new Set(values)].sort((a, b) => String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" }));
}

export function getTimeline(rows) {
  if (!rows.length) return { first: 0, last: 0, span: 0, width: MIN_TIMELINE_WIDTH, ticks: [] };
  const first = Math.min(...rows.map((row) => row.startMinute));
  const last = Math.max(...rows.map((row) => row.endMinute));
  const span = last - first;
  const pixelsPerMinute = Math.max(PIXELS_PER_MINUTE, MIN_TIMELINE_WIDTH / span);
  const width = Math.max(MIN_TIMELINE_WIDTH, span * pixelsPerMinute);
  const targetTickCount = Math.max(2, Math.floor(width / 120));
  const roughInterval = span / targetTickCount;
  const intervals = [1, 2, 5, 10, 15, 30, 60, 120, 240, 360, 720, 1440];
  const interval = intervals.find((value) => {
    if (value < roughInterval) return false;
    const fullGap = value * pixelsPerMinute;
    const remainder = span % value;
    return fullGap >= 100 && (remainder === 0 || remainder * pixelsPerMinute >= 100);
  }) || Math.ceil(roughInterval / 1440) * 1440;
  const ticks = [{ minute: first }];
  let minute = first + interval;
  while (minute < last) {
    if (minute > first) ticks.push({ minute });
    minute += interval;
  }
  if (last > first) ticks.push({ minute: last });
  return { first, last, span, width, pixelsPerMinute, ticks };
}

export function formatScheduleTime(referenceTime, minute, includeDate = false) {
  const reference = Date.parse(referenceTime);
  if (!Number.isFinite(reference) || !Number.isFinite(Number(minute))) return "—";
  const date = new Date(reference + Number(minute) * 60_000);
  const options = includeDate
    ? { timeZone: "Asia/Kolkata", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }
    : { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false };
  return new Intl.DateTimeFormat("en-GB", options).format(date);
}

export function findResourceConflicts(rows) {
  const conflicts = [];
  for (const resourceKey of ["Machine", "Operator ID"]) {
    const label = resourceKey === "Machine" ? "machine" : "operator";
    const grouped = new Map();
    rows.forEach((row) => {
      const resource = row[resourceKey];
      if (!resource || resource === "—") return;
      grouped.set(resource, [...(grouped.get(resource) || []), row]);
    });
    grouped.forEach((items, resource) => {
      const sorted = [...items].sort((a, b) => a.startMinute - b.startMinute || a.endMinute - b.endMinute);
      for (let i = 0; i < sorted.length; i += 1) {
        for (let j = i + 1; j < sorted.length && sorted[j].startMinute < sorted[i].endMinute; j += 1) {
          const start = Math.max(sorted[i].startMinute, sorted[j].startMinute);
          const end = Math.min(sorted[i].endMinute, sorted[j].endMinute);
          conflicts.push({ resourceType: label, resource, jobs: [sorted[i], sorted[j]], startMinute: start, endMinute: end });
        }
      }
    });
  }
  return conflicts;
}
