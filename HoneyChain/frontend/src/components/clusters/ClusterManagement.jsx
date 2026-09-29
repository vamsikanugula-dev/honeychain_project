import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Building2, Eye, Pencil, Plus, RotateCcw, Search, UserCog, Users } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { DataTable } from '@/components/common/DataTable';
import { Link } from 'react-router-dom';
import { StatCard } from '@/components/common/StatCard';
import { ClusterFormModal } from '@/components/clusters/ClusterFormModal';
import { ClusterMembersModal } from '@/components/clusters/ClusterMembersModal';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as clusterService from '@/services/clusterService';

const PAGE_SIZE = 10;
const EMPTY_FILTERS = { search: '', district: '', state: '' };

/**
 * Cluster management: create, edit, activate/deactivate and manage members.
 *
 * Scope stops there — no production or coverage analytics in this phase, so the
 * page shows counts it can actually query and nothing it cannot.
 */
export function ClusterManagement({ detailBasePath = null }) {
  const toast = useToast();
  const navigate = useNavigate();

  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const [statusFilter, setStatusFilter] = useState('');
  const [page, setPage] = useState(1);

  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [membersFor, setMembersFor] = useState(null);
  const [statusTarget, setStatusTarget] = useState(null);
  const [statusSaving, setStatusSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { clusters, meta: pageMeta } = await clusterService.listClusters({
        page,
        pageSize: PAGE_SIZE,
        search: applied.search || undefined,
        district: applied.district || undefined,
        state: applied.state || undefined,
        isActive: statusFilter === '' ? undefined : statusFilter === 'active',
      });
      setRows(clusters);
      setMeta(pageMeta);
    } catch (caught) {
      setError(normaliseError(caught));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [page, applied, statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const totals = useMemo(
    () => ({
      total: meta?.total_items ?? 0,
      active: rows.filter((row) => row.is_active).length,
      members: rows.reduce((sum, row) => sum + (row.member_count || 0), 0),
    }),
    [meta, rows],
  );

  const toggleStatus = async () => {
    if (!statusTarget) return;
    setStatusSaving(true);
    try {
      await clusterService.setClusterStatus(statusTarget.id, !statusTarget.is_active);
      toast.success(
        `${statusTarget.cluster_code} ${statusTarget.is_active ? 'deactivated' : 'activated'}`,
      );
      setStatusTarget(null);
      load();
    } catch (caught) {
      toast.error('Could not change the cluster status', normaliseError(caught).message);
    } finally {
      setStatusSaving(false);
    }
  };

  const columns = useMemo(
    () => [
      {
        key: 'cluster_code',
        header: 'Code',
        render: (row) => <span className="font-medium text-ink">{row.cluster_code}</span>,
      },
      {
        key: 'cluster_name',
        header: 'Cluster',
        render: (row) => (
          <div className="min-w-0">
            {/* One cluster, one record: this link opens the cluster's view of
                its members' hives, devices, telemetry and analyses. */}
            {detailBasePath ? (
              <Link
                to={`${detailBasePath}/${row.id}`}
                className="truncate font-medium text-forest-700 underline-offset-2 hover:underline"
              >
                {row.cluster_name}
              </Link>
            ) : (
              <p className="truncate font-medium text-ink">{row.cluster_name}</p>
            )}
            <p className="truncate text-xs text-ink-muted">
              {[row.district, row.state].filter(Boolean).join(', ')}
            </p>
          </div>
        ),
      },
      {
        key: 'coordinator_name',
        header: 'Coordinator',
        render: (row) =>
          row.coordinator_name ? (
            <div className="min-w-0">
              <p className="truncate text-ink">{row.coordinator_name}</p>
              <p className="truncate text-xs text-ink-muted">{row.coordinator_phone || '—'}</p>
            </div>
          ) : (
            '—'
          ),
      },
      { key: 'member_count', header: 'Members', align: 'right', render: (row) => row.member_count ?? 0 },
      {
        key: 'is_active',
        header: 'Status',
        render: (row) => (
          <Badge variant={row.is_active ? 'success' : 'neutral'} size="sm">
            {row.is_active ? 'Active' : 'Inactive'}
          </Badge>
        ),
      },
      {
        key: 'actions',
        header: '',
        align: 'right',
        render: (row) => (
          <div className="flex justify-end gap-2">
            {detailBasePath ? (
              <Button size="sm" variant="secondary" onClick={() => navigate(`${detailBasePath}/${row.id}`)}>
                <Eye size={14} className="mr-1" aria-hidden="true" /> View
              </Button>
            ) : null}
            <Button size="sm" variant="secondary" onClick={() => setMembersFor(row)}>
              <Users size={14} className="mr-1" aria-hidden="true" /> Members
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setEditing(row);
                setFormOpen(true);
              }}
            >
              <Pencil size={14} aria-hidden="true" />
              <span className="sr-only">Edit {row.cluster_code}</span>
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setStatusTarget(row)}
              aria-label={row.is_active ? `Deactivate ${row.cluster_code}` : `Activate ${row.cluster_code}`}
            >
              <UserCog size={14} aria-hidden="true" />
            </Button>
          </div>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [detailBasePath],
  );

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Clusters" value={totals.total} icon={<Building2 size={16} />} />
        <StatCard label="Active on this page" value={totals.active} tone="forest" />
        <StatCard
          label="Members on this page"
          value={totals.members}
          helper="Assigned beekeepers"
          tone="honey"
        />
      </div>

      <Card>
        <CardBody>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              setPage(1);
              setApplied(filters);
            }}
            className="grid gap-3 lg:grid-cols-4"
          >
            <Input
              label="Search"
              name="search"
              placeholder="Name, code or coordinator"
              leftIcon={<Search size={15} />}
              value={filters.search}
              onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))}
            />
            <Input
              label="District"
              name="district"
              value={filters.district}
              onChange={(event) => setFilters((prev) => ({ ...prev, district: event.target.value }))}
            />
            <Input
              label="State"
              name="state"
              value={filters.state}
              onChange={(event) => setFilters((prev) => ({ ...prev, state: event.target.value }))}
            />
            <Select
              label="Status"
              name="status"
              placeholder="Any status"
              options={[
                { value: 'active', label: 'Active' },
                { value: 'inactive', label: 'Inactive' },
              ]}
              value={statusFilter}
              onChange={(event) => {
                setPage(1);
                setStatusFilter(event.target.value);
              }}
            />
            <div className="flex flex-wrap items-end gap-2 lg:col-span-4">
              <Button type="submit" size="sm">
                Apply filters
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                leftIcon={<RotateCcw size={15} />}
                onClick={() => {
                  setFilters(EMPTY_FILTERS);
                  setApplied(EMPTY_FILTERS);
                  setStatusFilter('');
                  setPage(1);
                }}
              >
                Reset
              </Button>
              <Button
                type="button"
                size="sm"
                className="ml-auto"
                leftIcon={<Plus size={15} />}
                onClick={() => {
                  setEditing(null);
                  setFormOpen(true);
                }}
              >
                New cluster
              </Button>
            </div>
          </form>
        </CardBody>
      </Card>

      {error ? <Alert variant="danger">{error.message}</Alert> : null}

      <DataTable
        columns={columns}
        rows={rows}
        loading={loading}
        error={null}
        onRetry={load}
        meta={meta}
        onPageChange={setPage}
        emptyTitle="No clusters found"
        emptyDescription="Create a cluster to group beekeepers in a district under one coordinator."
      />

      <ClusterFormModal
        open={formOpen}
        cluster={editing}
        onClose={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        onSaved={load}
      />

      <ClusterMembersModal
        open={Boolean(membersFor)}
        cluster={membersFor}
        onClose={() => setMembersFor(null)}
        onChanged={load}
      />

      <ConfirmDialog
        open={Boolean(statusTarget)}
        title={statusTarget?.is_active ? 'Deactivate this cluster?' : 'Activate this cluster?'}
        description={
          statusTarget?.is_active
            ? 'Existing members keep their records, but the cluster cannot accept new ones until it is reactivated.'
            : 'The cluster will be able to accept new members again.'
        }
        confirmLabel={statusTarget?.is_active ? 'Deactivate' : 'Activate'}
        loading={statusSaving}
        onConfirm={toggleStatus}
        onCancel={() => setStatusTarget(null)}
      />
    </div>
  );
}

export default ClusterManagement;
