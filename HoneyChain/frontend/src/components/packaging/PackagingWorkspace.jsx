import { useCallback, useEffect, useState } from 'react';
import { Boxes, CheckCheck, History, Inbox, PackageCheck, RefreshCw } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { CancelPackagingDialog } from '@/components/packaging/CancelPackagingDialog';
import { StatCard } from '@/components/common/StatCard';
import { ApprovedBatchTable } from '@/components/packaging/ApprovedBatchTable';
import { CreatePackagingDialog } from '@/components/packaging/CreatePackagingDialog';
import { PackageRegisterTable } from '@/components/packaging/PackageRegisterTable';
import { PackagingRunPanel } from '@/components/packaging/PackagingRunPanel';
import { PackagingRunTable } from '@/components/packaging/PackagingRunTable';
import { PACKAGE_STATUS_META, PACKAGING_MESSAGES, PACKAGING_STATUS_META } from '@/constants/packaging';
import { ROLES } from '@/constants/roles';
import { useToast } from '@/hooks/useToast';
import * as packagingService from '@/services/packagingService';
import { normaliseError } from '@/utils/errors';
import { formatNumber } from '@/utils/format';

/**
 * The packaging workspace.
 *
 * One component, three audiences, and the difference between them is a permission
 * rather than a page: a **packaging unit** works the list (open a run, start it,
 * record what was filled, complete it, release the packages), an **administrator**
 * can do the same, and a **KVIC officer** reads the identical rows for their own
 * clusters with no actions rendered at all. A **beekeeper** reaching these screens
 * sees their own honey and nothing else.
 *
 * Nothing on this screen is a copy of a batch. A run points at the batch; the batch
 * holds its own status, and the server moves it through the transition table when
 * the packages actually exist.
 */

const PACKAGING_STATUS_FILTERS = [
  { value: '', label: 'All packaging statuses' },
  ...Object.entries(PACKAGING_STATUS_META).map(([value, meta]) => ({ value, label: meta.label })),
];

const PACKAGE_STATUS_FILTERS = [
  { value: '', label: 'All package statuses' },
  ...Object.entries(PACKAGE_STATUS_META).map(([value, meta]) => ({ value, label: meta.label })),
];

export function PackagingWorkspace({ role = ROLES.PACKAGING_UNIT, view = 'overview' }) {
  const toast = useToast();
  const canWrite = role === ROLES.PACKAGING_UNIT || role === ROLES.ADMIN;

  const [summary, setSummary] = useState(null);
  const [approved, setApproved] = useState([]);
  const [approvedMeta, setApprovedMeta] = useState(null);
  const [runs, setRuns] = useState([]);
  const [runsMeta, setRunsMeta] = useState(null);
  const [packages, setPackages] = useState([]);
  const [packagesMeta, setPackagesMeta] = useState(null);
  const [units, setUnits] = useState([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [openRun, setOpenRun] = useState(null);
  const [packingBatch, setPackingBatch] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [dialogError, setDialogError] = useState(null);
  const [cancelTarget, setCancelTarget] = useState(null);

  const [filters, setFilters] = useState({ search: '', status: '', page: 1 });
  const [packageFilters, setPackageFilters] = useState({ search: '', status: '', page: 1 });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [summaryData, approvedResult, runsResult, packagesResult, unitsResult] = await Promise.all([
        packagingService.getPackagingSummary().catch(() => null),
        packagingService
          .listApprovedBatches({
            page: filters.page,
            search: filters.search || undefined,
          })
          .catch(() => ({ batches: [], meta: null })),
        packagingService
          .listPackaging({
            page: filters.page,
            search: filters.search || undefined,
            status: filters.status || undefined,
          })
          .catch(() => ({ runs: [], meta: null })),
        packagingService
          .listPackages({
            page: packageFilters.page,
            search: packageFilters.search || undefined,
            status: packageFilters.status || undefined,
          })
          .catch(() => ({ packages: [], meta: null })),
        packagingService.listUnits({ pageSize: 50 }).catch(() => ({ units: [] })),
      ]);

      setSummary(summaryData);
      setApproved(approvedResult.batches || []);
      setApprovedMeta(approvedResult.meta || null);
      setRuns(runsResult.runs || []);
      setRunsMeta(runsResult.meta || null);
      setPackages(packagesResult.packages || []);
      setPackagesMeta(packagesResult.meta || null);
      setUnits(unitsResult.units || []);
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [filters.page, filters.search, filters.status, packageFilters.page, packageFilters.search, packageFilters.status]);

  useEffect(() => {
    load();
  }, [load]);

  async function runAction(run, action, successMessage, payload = {}) {
    setBusyId(run.id);
    try {
      const updated = await action(run.id, payload);
      toast.success(successMessage);
      if (openRun?.id === run.id) {
        setOpenRun(updated);
      }
      await load();
    } catch (caught) {
      toast.error(normaliseError(caught).message);
    } finally {
      setBusyId(null);
    }
  }

  async function handleCreate(payload) {
    setSubmitting(true);
    setDialogError(null);
    try {
      const created = await packagingService.createPackaging(payload);
      toast.success(PACKAGING_MESSAGES.created);
      setPackingBatch(null);
      setOpenRun(created);
      await load();
    } catch (caught) {
      setDialogError(normaliseError(caught).message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCancel(reason) {
    if (!cancelTarget) return;
    await runAction(
      cancelTarget,
      (id, body) => packagingService.cancelPackaging(id, body),
      PACKAGING_MESSAGES.cancelled,
      reason ? { reason } : {},
    );
    setCancelTarget(null);
  }

  async function handleRelease(releaseRun) {
    await runAction(
      releaseRun,
      (id) => packagingService.releasePackaging(id, {}),
      PACKAGING_MESSAGES.released,
    );
  }

  async function handleReleasePackage(packageRow) {
    setBusyId(packageRow.id);
    try {
      await packagingService.releasePackage(packageRow.id, {});
      toast.success(PACKAGING_MESSAGES.released);
      await load();
    } catch (caught) {
      toast.error(normaliseError(caught).message);
    } finally {
      setBusyId(null);
    }
  }

  const showApproved = view === 'overview' || view === 'approved';
  const showRuns = view === 'overview' || view === 'runs' || view === 'history';
  const showPackages = view === 'overview' || view === 'packages';
  const historyOnly = view === 'history';

  return (
    <div className="space-y-6">
      {error ? <Alert variant="error">{error.message || PACKAGING_MESSAGES.loadFailed}</Alert> : null}

      {view === 'overview' ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Approved batches waiting"
            value={summary?.awaiting_packaging ?? '—'}
            helper={`${summary?.approved_batches ?? 0} approved batch(es) in scope`}
            icon={<Inbox size={16} />}
            loading={loading && !summary}
          />
          <StatCard
            label="Packing under way"
            value={summary?.in_progress ?? '—'}
            helper={`${summary?.completed ?? 0} run(s) completed`}
            icon={<Boxes size={16} />}
            loading={loading && !summary}
          />
          <StatCard
            label="Packages created"
            value={summary?.packages_created ?? '—'}
            helper={`${summary?.packages_ready ?? 0} ready, ${summary?.packages_in_distribution ?? 0} in distribution`}
            icon={<PackageCheck size={16} />}
            loading={loading && !summary}
          />
          <StatCard
            label="Honey left to pack"
            value={`${formatNumber(summary?.quantity_remaining)} ${summary?.unit ? '' : ''}`.trim()}
            helper={`${formatNumber(summary?.quantity_packaged)} packaged so far`}
            icon={<CheckCheck size={16} />}
            loading={loading && !summary}
            tone="honey"
          />
        </div>
      ) : null}

      {showApproved && !historyOnly ? (
        <Card>
          <CardHeader
            title="Approved batches"
            description="Batches the laboratory approved, with what is left to pack."
            icon={<Inbox size={18} />}
            action={
              <Button
                variant="secondary"
                size="sm"
                leftIcon={<RefreshCw size={14} />}
                onClick={load}
                loading={loading}
              >
                Refresh
              </Button>
            }
          />
          <CardBody className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <Input
                label="Search"
                name="search"
                placeholder="Batch or collection code"
                value={filters.search}
                onChange={(event) =>
                  setFilters((current) => ({ ...current, search: event.target.value, page: 1 }))
                }
              />
            </div>
            <ApprovedBatchTable
              batches={approved}
              loading={loading}
              meta={approvedMeta}
              onPageChange={(page) => setFilters((current) => ({ ...current, page }))}
              canWrite={canWrite}
              busyId={busyId}
              onPack={(row) => {
                setDialogError(null);
                setPackingBatch(row);
              }}
            />
          </CardBody>
        </Card>
      ) : null}

      {showRuns ? (
        <Card>
          <CardHeader
            title={historyOnly ? 'Packaging history' : 'Packaging runs'}
            description={
              historyOnly
                ? 'Every run recorded, newest first, cancelled ones included.'
                : 'Runs under way and their quantities.'
            }
            icon={<History size={18} />}
          />
          <CardBody className="space-y-4">
            {!historyOnly ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <Input
                  label="Search"
                  name="search"
                  placeholder="Run, batch or collection code"
                  value={filters.search}
                  onChange={(event) =>
                    setFilters((current) => ({ ...current, search: event.target.value, page: 1 }))
                  }
                />
                <Select
                  label="Status"
                  name="status"
                  options={PACKAGING_STATUS_FILTERS}
                  value={filters.status}
                  onChange={(event) =>
                    setFilters((current) => ({ ...current, status: event.target.value, page: 1 }))
                  }
                />
              </div>
            ) : null}
            <PackagingRunTable
              runs={runs}
              loading={loading}
              meta={runsMeta}
              onPageChange={(page) => setFilters((current) => ({ ...current, page }))}
              canWrite={canWrite}
              busyId={busyId}
              onOpen={setOpenRun}
              onStart={(row) =>
                runAction(row, (id) => packagingService.startPackaging(id, {}), PACKAGING_MESSAGES.started)
              }
              onComplete={(row) =>
                runAction(
                  row,
                  (id) => packagingService.completePackaging(id, {}),
                  PACKAGING_MESSAGES.completed,
                )
              }
              onCancel={setCancelTarget}
              onRelease={handleRelease}
            />
          </CardBody>
        </Card>
      ) : null}

      {showPackages ? (
        <Card>
          <CardHeader
            title="Packages"
            description="Each package with its own stable code and where it has got to."
            icon={<PackageCheck size={18} />}
          />
          <CardBody className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <Input
                label="Search"
                name="search"
                placeholder="Package, batch or run code"
                value={packageFilters.search}
                onChange={(event) =>
                  setPackageFilters((current) => ({
                    ...current,
                    search: event.target.value,
                    page: 1,
                  }))
                }
              />
              <Select
                label="Status"
                name="package_status"
                options={PACKAGE_STATUS_FILTERS}
                value={packageFilters.status}
                onChange={(event) =>
                  setPackageFilters((current) => ({
                    ...current,
                    status: event.target.value,
                    page: 1,
                  }))
                }
              />
            </div>
            <PackageRegisterTable
              packages={packages}
              loading={loading}
              meta={packagesMeta}
              onPageChange={(page) => setPackageFilters((current) => ({ ...current, page }))}
              canWrite={canWrite}
              busyId={busyId}
              onRelease={handleReleasePackage}
            />
          </CardBody>
        </Card>
      ) : null}

      {openRun ? (
        <Card>
          <CardHeader
            title="Run detail"
            description="Read from the run's own record, with its packages."
            action={
              <Button variant="ghost" size="sm" onClick={() => setOpenRun(null)}>
                Close
              </Button>
            }
          />
          <CardBody>
            <PackagingRunPanel run={openRun} packages={openRun.packages || []} />
          </CardBody>
        </Card>
      ) : null}

      <CreatePackagingDialog
        open={Boolean(packingBatch)}
        batch={packingBatch}
        units={units}
        onClose={() => setPackingBatch(null)}
        onSubmit={handleCreate}
        submitting={submitting}
        error={dialogError}
      />

      <CancelPackagingDialog
        open={Boolean(cancelTarget)}
        run={cancelTarget}
        submitting={busyId === cancelTarget?.id}
        onClose={() => setCancelTarget(null)}
        onConfirm={handleCancel}
      />
    </div>
  );
}

export default PackagingWorkspace;
