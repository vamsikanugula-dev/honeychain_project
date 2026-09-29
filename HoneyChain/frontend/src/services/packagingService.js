/**
 * Packaging service — approved batches, packaging runs and the packages they make.
 *
 * Two things are deliberately absent from every payload this module builds:
 * `status` and any package or run code. The server decides the state a run is in
 * and issues `HC-PACK-…` / `HC-PKG-…` itself, so a caller cannot name a state the
 * workflow has not reached or choose an identifier that already exists.
 *
 * The quantities are sent as typed, never rounded or converted on the client: a
 * package size of 0.5 kg packed twelve times is 6 kg, and the server is the one
 * that checks the arithmetic.
 */

import { ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';

function listParams({ page = 1, pageSize = 20, search, ...rest } = {}) {
  return {
    page,
    page_size: pageSize,
    ...(search ? { search } : {}),
    ...Object.fromEntries(Object.entries(rest).filter(([, value]) => value !== undefined && value !== null && value !== '')),
  };
}

/** Batches the laboratory approved, with the quantities still to pack. */
export async function listApprovedBatches({ page = 1, pageSize = 20, search } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.packaging.approvedBatches, {
    params: listParams({ page, pageSize, search }),
  });
  return { batches: data, meta };
}

/** Counters for the packaging dashboard: work waiting, packing under way, packages made. */
export async function getPackagingSummary() {
  const { data } = await http.get(ENDPOINTS.packaging.summary);
  return data;
}

/** Packaging runs the caller may read, newest first. */
export async function listPackaging({ page = 1, pageSize = 20, search, batchId, status } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.packaging.list, {
    params: listParams({ page, pageSize, search, batch_id: batchId, status }),
  });
  return { runs: data, meta };
}

/** One run: its batch, its quantities and the packages it produced. */
export async function getPackaging(packagingId) {
  const { data } = await http.get(ENDPOINTS.packaging.detail(packagingId));
  return data;
}

/** Open a run against an approved batch. */
export async function createPackaging(payload) {
  const { data } = await http.post(ENDPOINTS.packaging.list, payload);
  return data;
}

/** Record a correction while the run is still open. */
export async function updatePackaging(packagingId, payload) {
  const { data } = await http.patch(ENDPOINTS.packaging.detail(packagingId), payload);
  return data;
}

export async function startPackaging(packagingId) {
  const { data } = await http.post(ENDPOINTS.packaging.start(packagingId), {});
  return data;
}

/** Complete a run: the packages are created and the batch moves to PACKAGED. */
export async function completePackaging(packagingId, payload = {}) {
  const { data } = await http.post(ENDPOINTS.packaging.complete(packagingId), payload);
  return data;
}

export async function cancelPackaging(packagingId, payload = {}) {
  const { data } = await http.post(ENDPOINTS.packaging.cancel(packagingId), payload);
  return data;
}

/** Release every completed package of a run for distribution. */
export async function releasePackaging(packagingId, payload = {}) {
  const { data } = await http.post(ENDPOINTS.packaging.release(packagingId), payload);
  return data;
}

/** The package register: individual packages with their own codes. */
export async function listPackages({
  page = 1,
  pageSize = 20,
  search,
  batchId,
  packagingId,
  status,
} = {}) {
  const { data, meta } = await http.get(ENDPOINTS.packaging.packages, {
    params: listParams({
      page,
      pageSize,
      search,
      batch_id: batchId,
      packaging_id: packagingId,
      status,
    }),
  });
  return { packages: data, meta };
}

export async function getPackage(packageId) {
  const { data } = await http.get(ENDPOINTS.packaging.package(packageId));
  return data;
}

/** Release a single package. */
export async function releasePackage(packageId, payload = {}) {
  const { data } = await http.post(ENDPOINTS.packaging.packageRelease(packageId), payload);
  return data;
}

/** Issue (or return) the stable opaque QR resolver for one existing package. */
export async function generatePackageQr(packageId) {
  const { data } = await http.post(ENDPOINTS.packaging.packageQr(packageId), {});
  return data;
}

/** The packages of one batch — the batch screen's own package register. */
export async function listPackagesForBatch(batchId, { page = 1, pageSize = 20 } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.packaging.packagesForBatch(batchId), {
    params: listParams({ page, pageSize }),
  });
  return { packages: data, meta };
}

/** Packaging units. A run names the unit that did the work; units are registry rows. */
export async function listUnits({ page = 1, pageSize = 50, search } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.packaging.units, {
    params: listParams({ page, pageSize, search }),
  });
  return { units: data, meta };
}

export async function createUnit(payload) {
  const { data } = await http.post(ENDPOINTS.packaging.units, payload);
  return data;
}
