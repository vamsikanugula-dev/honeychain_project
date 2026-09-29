/**
 * Laboratory vocabulary.
 *
 * Mirrors the backend enums (`LabTestStatus`, `LabResult`, `LabParameterStatus`)
 * and the wording the laboratory screens must show. A parameter whose reference
 * range has not been configured is `NOT_EVALUATED` — the platform has no default
 * limits, so it never labels a measurement "pass" or "fail" on its own.
 */

export const LAB_TEST_STATUSES = Object.freeze({
  PENDING: 'PENDING',
  IN_PROGRESS: 'IN_PROGRESS',
  COMPLETED: 'COMPLETED',
});

export const LAB_TEST_STATUS_META = Object.freeze({
  PENDING: { label: 'Pending', variant: 'pending', hint: 'Sample recorded; no measurements yet.' },
  IN_PROGRESS: { label: 'In progress', variant: 'warning', hint: 'Measurements are being recorded.' },
  COMPLETED: { label: 'Completed', variant: 'info', hint: 'Closed. Its results are read, never rewritten.' },
});

export const LAB_RESULTS = Object.freeze({
  PENDING: 'PENDING',
  PASS: 'PASS',
  FAIL: 'FAIL',
  INCONCLUSIVE: 'INCONCLUSIVE',
});

export const LAB_RESULT_META = Object.freeze({
  PENDING: { label: 'Pending', variant: 'pending', hint: 'No decision yet.' },
  PASS: { label: 'Pass', variant: 'success', hint: 'Every evaluated and required parameter passed.' },
  FAIL: { label: 'Fail', variant: 'danger', hint: 'At least one required parameter failed.' },
  INCONCLUSIVE: {
    label: 'Inconclusive',
    variant: 'neutral',
    hint: 'A verdict needs measurements that were not recorded, or ranges that are not configured.',
  },
});

export const LAB_PARAMETER_STATUS_META = Object.freeze({
  PASS: { label: 'Pass', variant: 'success' },
  FAIL: { label: 'Fail', variant: 'danger' },
  NOT_EVALUATED: { label: 'Not evaluated', variant: 'neutral' },
});

/** Sample units — grams and kilograms, as the collection module stores them. */
export const SAMPLE_UNITS = Object.freeze([
  { value: 'GRAM', label: 'Grams (g)' },
  { value: 'KG', label: 'Kilograms (kg)' },
]);

/**
 * The exact empty, loading and failure strings the laboratory screens show.
 *
 * They are named rather than inlined so the required copy can be reviewed in one
 * place — and so no screen can quietly paraphrase "No laboratory results recorded."
 */
export const LAB_MESSAGES = Object.freeze({
  awaitingEmpty: 'No batches awaiting laboratory testing.',
  awaitingEmptyDescription:
    'A batch arrives here when its processing run is completed. Nothing is waiting right now.',
  testsEmpty: 'No laboratory tests recorded yet.',
  samplesEmpty: 'No samples recorded yet.',
  completedEmpty: 'No completed laboratory tests yet.',
  resultsEmpty: 'No laboratory results recorded.',
  facilitiesEmpty: 'No laboratories registered yet.',
  loadingBatch: 'Loading batch information...',
  loadingTests: 'Loading laboratory tests...',
  loadingLaboratory: 'Loading laboratory results...',
  loadFailed: 'Unable to load laboratory information.',
});

/** How a parameter row reads: value with its unit, or an explicit absence. */
/** The badge copy for a test status, with a neutral fallback for an unknown one. */
export function labStatusMeta(status) {
  return LAB_TEST_STATUS_META[status] || { label: status || 'Unknown', variant: 'neutral' };
}

export function measurementText(result) {
  if (!result || result.value === null || result.value === undefined) return '—';
  return `${Number(result.value).toLocaleString(undefined, { maximumFractionDigits: 4 })} ${
    result.unit_label || ''
  }`.trim();
}

/** The configured range as text, or `null` when nothing has been configured. */
export function referenceText(result) {
  if (!result) return null;
  const { reference_min: min, reference_max: max } = result;
  if (min === null || min === undefined) return max === null || max === undefined ? null : `≤ ${max}`;
  if (max === null || max === undefined) return `≥ ${min}`;
  return `${min} – ${max}`;
}

export default {
  LAB_TEST_STATUSES,
  LAB_TEST_STATUS_META,
  LAB_RESULTS,
  LAB_RESULT_META,
  LAB_PARAMETER_STATUS_META,
  SAMPLE_UNITS,
  LAB_MESSAGES,
  measurementText,
  referenceText,
};
