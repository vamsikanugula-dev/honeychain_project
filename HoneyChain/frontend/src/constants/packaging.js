/**
 * Packaging vocabulary.
 *
 * Mirrors the backend enums (`PackagingStatus`, `PackagingType`, `PackageStatus`)
 * and the wording the packaging screens must show. A status that the database does
 * not have is not invented here — there is no "READY" packaging run and no
 * "SHIPPED" package, because the platform has no such states.
 */

export const PACKAGING_STATUSES = Object.freeze({
  PENDING: 'PENDING',
  IN_PROGRESS: 'IN_PROGRESS',
  COMPLETED: 'COMPLETED',
  CANCELLED: 'CANCELLED',
});

/** Label and tone per status, so a cancelled run never reads as a success. */
export const PACKAGING_STATUS_META = Object.freeze({
  PENDING: { label: 'Pending', variant: 'pending', hint: 'Opened; packing has not started.' },
  IN_PROGRESS: { label: 'In progress', variant: 'warning', hint: 'The honey is being packed.' },
  COMPLETED: {
    label: 'Completed',
    variant: 'success',
    hint: 'The packages exist and the quantities are recorded.',
  },
  CANCELLED: { label: 'Cancelled', variant: 'neutral', hint: 'The run did not happen.' },
});

export const PACKAGE_STATUSES = Object.freeze({
  CREATED: 'CREATED',
  READY_FOR_DISTRIBUTION: 'READY_FOR_DISTRIBUTION',
  IN_DISTRIBUTION: 'IN_DISTRIBUTION',
  DELIVERED: 'DELIVERED',
  CANCELLED: 'CANCELLED',
});

/**
 * Package states.
 *
 * `CREATED` is deliberately not "ready": a package exists as soon as the honey is
 * in it, and becomes available to distribution only when the packaging unit
 * releases it. Existence is not readiness, and the two words are not synonyms.
 */
export const PACKAGE_STATUS_META = Object.freeze({
  CREATED: { label: 'Created', variant: 'pending', hint: 'Packed, not yet released.' },
  READY_FOR_DISTRIBUTION: {
    label: 'Ready for distribution',
    variant: 'info',
    hint: 'Released by the packaging unit and available to ship.',
  },
  IN_DISTRIBUTION: {
    label: 'In distribution',
    variant: 'warning',
    hint: 'On a shipment that has left.',
  },
  DELIVERED: { label: 'Delivered', variant: 'success', hint: 'Received by the retailer.' },
  CANCELLED: { label: 'Cancelled', variant: 'neutral', hint: 'Withdrawn before it moved.' },
});

/** Packaging types the platform records. */
export const PACKAGING_TYPES = Object.freeze([
  { value: 'JAR', label: 'Jar' },
  { value: 'BOTTLE', label: 'Bottle' },
  { value: 'POUCH', label: 'Pouch' },
  { value: 'TIN', label: 'Tin' },
  { value: 'BULK_CONTAINER', label: 'Bulk container' },
  { value: 'OTHER', label: 'Other' },
]);

export const PACKAGING_TYPE_LABELS = Object.freeze(
  PACKAGING_TYPES.reduce((labels, type) => {
    labels[type.value] = type.label;
    return labels;
  }, {}),
);

/**
 * The copy each packaging screen shows, kept in one place so the wording cannot
 * drift between the dashboard, the tables and the detail pages.
 */
export const PACKAGING_VIEW_COPY = Object.freeze({
  overview: {
    title: 'Packaging workspace',
    description:
      'Batches the laboratory approved, the honey packed into individual packages, and what is still waiting to be packed.',
  },
  approved: {
    title: 'Approved batches',
    description:
      'Batches the laboratory approved, with what is left to pack. Nothing else may be packed — a rejected batch is never shown here and never accepted by the server.',
  },
  runs: {
    title: 'Packaging',
    description:
      'Runs under way and their quantities: what is being packed, into what, and how many packages it will make.',
  },
  packages: {
    title: 'Packages',
    description:
      'Every individual package with its own stable code, the run it came from and where it has got to.',
  },
  history: {
    title: 'Packaging history',
    description:
      'Every packaging run recorded, newest first — including cancelled ones, which are kept rather than deleted.',
  },
});

/**
 * Fields a completed or cancelled packaging run will not accept changes to
 * (mirrors the service). Shown to a caller rather than silently ignored.
 */
export const IMMUTABLE_PACKAGING_FIELDS = Object.freeze([
  'batch',
  'packaged quantity',
  'package size',
  'number of packages',
  'packaging type',
]);

/** The empty, loading and failure strings the packaging screens show. */
export const PACKAGING_MESSAGES = Object.freeze({
  emptyApproved: 'No approved batch is waiting to be packed.',
  emptyRuns: 'No packaging run has been recorded yet.',
  emptyPackages: 'No packages have been created yet.',
  emptyHistory: 'No packaging runs recorded yet.',
  loadingApproved: 'Loading approved batches...',
  loadingRuns: 'Loading packaging runs...',
  loadingPackages: 'Loading packages...',
  loadFailed: 'Unable to load the packaging records.',
  noUnits:
    'No packaging unit is registered yet. A run must be recorded against the unit that did the work.',
  created: 'Packaging run opened.',
  started: 'Packing started.',
  completed: 'Packing completed and the packages created.',
  cancelled: 'Packaging run cancelled.',
  released: 'Packages released for distribution.',
});
