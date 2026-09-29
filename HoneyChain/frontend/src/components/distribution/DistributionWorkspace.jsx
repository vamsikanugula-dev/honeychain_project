import { useCallback, useEffect, useState } from 'react';
import { Boxes, PackageCheck, RefreshCw, Route, Truck } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { StatCard } from '@/components/common/StatCard';
import { CreateShipmentDialog } from '@/components/distribution/CreateShipmentDialog';
import { ShipmentTable } from '@/components/distribution/ShipmentTable';
import {
  DISTRIBUTION_MESSAGES,
  DISTRIBUTION_STATUS_META,
  DISTRIBUTION_VIEW_COPY,
} from '@/constants/distribution';
import { ROLES } from '@/constants/roles';
import { useToast } from '@/hooks/useToast';
import * as distributionService from '@/services/distributionService';
import * as packagingService from '@/services/packagingService';
import { normaliseError } from '@/utils/errors';
import { formatNumber } from '@/utils/format';

/**
 * The distributor's workspace.
 *
 * A shipment is raised against a *released package* — one the packaging unit has
 * already let go of — and then walks the journey the server allows: ready →
 * dispatched → in transit → delivered, or cancelled while nothing has arrived. The
 * buttons mirror that order exactly; there is no control that jumps a step, and the
 * server refuses the same jumps independently.
 *
 * The batch is not copied here. A shipment carries a package, the package carries
 * the batch, and every screen reads those same rows.
 */

const STATUS_FILTERS = [
  { value: '', label: 'All shipment statuses' },
  ...Object.entries(DISTRIBUTION_STATUS_META).map(([value, meta]) => ({ value, label: meta.label })),
];

const VIEW_COPY = {
  overview: DISTRIBUTION_VIEW_COPY.overview,
  ready: DISTRIBUTION_VIEW_COPY.ready,
  shipments: DISTRIBUTION_VIEW_COPY.shipments,
  transit: DISTRIBUTION_VIEW_COPY.transit,
  delivered: DISTRIBUTION_VIEW_COPY.delivered,
  history: DISTRIBUTION_VIEW_COPY.history,
};

export function DistributionWorkspace({ role = ROLES.DISTRIBUTOR, view = 'overview' }) {
  const toast = useToast();
  const canWrite = role === ROLES.DISTRIBUTOR || role === ROLES.ADMIN;

  const [summary, setSummary] = useState(null);
  const [shipments, setShipments] = useState([]);
  const [meta, setMeta] = useState(null);
  const [releasedPackages, setReleasedPackages] = useState([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [creating, setCreating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [dialogError, setDialogError] = useState(null);

  const [filters, setFilters] = useState({ search: '', status: '', page: 1 });

  const statusFilter =
    view === 'ready'
      ? 'READY_FOR_DISPATCH'
      : view === 'transit'
        ? 'IN_TRANSIT'
        : view === 'delivered'
          ? 'DELIVERED'
          : filters.status;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [summaryData, listResult, packageResult] = await Promise.all([
        distributionService.getDistributionSummary().catch(() => null),
        distributionService
          .listDistributions({
            page: filters.page,
            search: filters.search || undefined,
            status: statusFilter || undefined,
          })
          .catch(() => ({ shipments: [], meta: null })),
        canWrite
          ? packagingService
              .listPackages({ pageSize: 100, status: 'READY_FOR_DISTRIBUTION' })
              .catch(() => ({ packages: [] }))
          : Promise.resolve({ packages: [] }),
      ]);
      setSummary(summaryData);
      setShipments(listResult.shipments || []);
      setMeta(listResult.meta || null);
      setReleasedPackages((packageResult.packages || []).filter((row) => row.remaining_quantity > 0));
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [canWrite, filters.page, filters.search, statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  async function runAction(shipment, action, successMessage, payload = {}) {
    setBusyId(shipment.id);
    try {
      await action(shipment.id, payload);
      toast.success(successMessage);
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
      await distributionService.createDistribution(payload);
      toast.success(DISTRIBUTION_MESSAGES.created);
      setCreating(false);
      await load();
    } catch (caught) {
      setDialogError(normaliseError(caught).message);
    } finally {
      setSubmitting(false);
    }
  }

  const copy = VIEW_COPY[view] || VIEW_COPY.overview;

  return (
    <div className="space-y-6">
      {error ? <Alert variant="error">{error.message || DISTRIBUTION_MESSAGES.loadFailed}</Alert> : null}

      {view === 'overview' ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Ready for dispatch"
            value={summary?.ready_for_dispatch ?? '—'}
            helper={`${summary?.total ?? 0} shipment(s) in total`}
            icon={<Boxes size={16} />}
            loading={loading && !summary}
          />
          <StatCard
            label="On the road"
            value={(summary?.dispatched ?? 0) + (summary?.in_transit ?? 0)}
            helper={`${summary?.in_transit ?? 0} in transit`}
            icon={<Truck size={16} />}
            loading={loading && !summary}
          />
          <StatCard
            label="Delivered"
            value={summary?.delivered ?? '—'}
            helper={`${formatNumber(summary?.quantity_delivered)} ${summary?.unit || ''}`.trim()}
            icon={<PackageCheck size={16} />}
            loading={loading && !summary}
            tone="honey"
          />
          <StatCard
            label="Dispatched quantity"
            value={`${formatNumber(summary?.quantity_dispatched)} ${summary?.unit || ''}`.trim()}
            helper="Summed from the shipments, not from the packages they came from."
            icon={<Route size={16} />}
            loading={loading && !summary}
          />
        </div>
      ) : null}

      <Card>
        <CardHeader
          title={copy.title}
          description={copy.description}
          icon={<Truck size={18} />}
          action={
            canWrite ? (
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  leftIcon={<RefreshCw size={14} />}
                  onClick={load}
                  loading={loading}
                >
                  Refresh
                </Button>
                <Button
                  size="sm"
                  leftIcon={<Boxes size={14} />}
                  onClick={() => {
                    setDialogError(null);
                    setCreating(true);
                  }}
                >
                  New shipment
                </Button>
              </div>
            ) : (
              <Button variant="secondary" size="sm" leftIcon={<RefreshCw size={14} />} onClick={load}>
                Refresh
              </Button>
            )
          }
        />
        <CardBody className="space-y-4">
          {view !== 'ready' && view !== 'transit' && view !== 'delivered' ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <Input
                label="Search"
                name="search"
                placeholder="Shipment, package or batch code"
                value={filters.search}
                onChange={(event) =>
                  setFilters((current) => ({ ...current, search: event.target.value, page: 1 }))
                }
              />
              <Select
                label="Status"
                name="status"
                options={STATUS_FILTERS}
                value={filters.status}
                onChange={(event) =>
                  setFilters((current) => ({ ...current, status: event.target.value, page: 1 }))
                }
              />
            </div>
          ) : null}

          <ShipmentTable
            shipments={shipments}
            loading={loading}
            meta={meta}
            onPageChange={(page) => setFilters((current) => ({ ...current, page }))}
            canWrite={canWrite}
            busyId={busyId}
            emptyTitle={DISTRIBUTION_MESSAGES.emptyShipments}
            onDispatch={(row) =>
              runAction(
                row,
                (id, body) => distributionService.dispatch(id, body),
                DISTRIBUTION_MESSAGES.dispatched,
              )
            }
            onInTransit={(row) =>
              runAction(
                row,
                (id, body) => distributionService.markInTransit(id, body),
                DISTRIBUTION_MESSAGES.inTransit,
              )
            }
            onDeliver={(row) =>
              runAction(
                row,
                (id, body) => distributionService.deliver(id, body),
                DISTRIBUTION_MESSAGES.delivered,
              )
            }
            onCancel={(row) =>
              runAction(
                row,
                (id, body) => distributionService.cancel(id, body),
                DISTRIBUTION_MESSAGES.cancelled,
              )
            }
          />
        </CardBody>
      </Card>

      <CreateShipmentDialog
        open={creating}
        packages={releasedPackages}
        onClose={() => setCreating(false)}
        onSubmit={handleCreate}
        submitting={submitting}
        error={dialogError}
      />
    </div>
  );
}

export default DistributionWorkspace;
