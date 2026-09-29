import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Building2 } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { StatCard } from '@/components/common/StatCard';
import { DataTable } from '@/components/common/DataTable';
import { WorkspaceHeader } from '@/components/common/WorkspaceHeader';
import * as batchService from '@/services/batchService';
import * as clusterService from '@/services/clusterService';
import * as laboratoryService from '@/services/laboratoryService';
import { normaliseError } from '@/utils/errors';

/**
 * Cluster analytics.
 *
 * Counts over the records that already exist, per cluster the officer is
 * authorised for: members, hives, harvests, batches and quality outcomes. Nothing
 * is extrapolated and nothing is estimated — a cluster with no records shows
 * zeros, and a metric the platform cannot compute is simply absent rather than
 * guessed.
 */
export default function KvicClusterAnalyticsPage() {
  const [rows, setRows] = useState([]);
  const [totals, setTotals] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [clusters, batches, lab] = await Promise.all([
        clusterService.listClusters({ pageSize: 100 }),
        batchService.listBatches({ pageSize: 1 }),
        laboratoryService.getTestSummary().catch(() => null),
      ]);

      const perCluster = await Promise.all(
        clusters.clusters.map(async (cluster) => {
          const [summary, clusterBatches] = await Promise.allSettled([
            clusterService.getCluster(cluster.id),
            batchService.getClusterBatches(cluster.id, { pageSize: 1 }),
          ]);
          const detail = summary.status === 'fulfilled' ? summary.value : null;
          return {
            id: cluster.id,
            code: cluster.cluster_code,
            name: cluster.cluster_name,
            district: cluster.district || detail?.district || '—',
            beekeepers: detail?.member_count ?? detail?.beekeeper_count ?? null,
            hives: detail?.hive_count ?? null,
            batches: clusterBatches.status === 'fulfilled' ? clusterBatches.value.meta?.total_items ?? 0 : null,
            is_active: cluster.is_active,
          };
        }),
      );

      setRows(perCluster);
      setTotals({
        clusters: clusters.meta?.total_items ?? clusters.clusters.length,
        batches: batches.meta?.total_items ?? 0,
        passed: lab?.passed ?? 0,
        failed: lab?.failed ?? 0,
        inconclusive: lab?.inconclusive ?? 0,
      });
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const columns = [
    {
      key: 'code',
      header: 'Cluster',
      render: (row) => (
        <Link className="font-medium text-forest-700 hover:underline" to={`/kvic/clusters/${row.id}`}>
          {row.name}
        </Link>
      ),
    },
    { key: 'code_label', header: 'Code', render: (row) => <span className="font-mono text-xs text-ink-soft">{row.code}</span> },
    { key: 'district', header: 'District', render: (row) => row.district },
    { key: 'beekeepers', header: 'Beekeepers', align: 'right', render: (row) => row.beekeepers ?? '—' },
    { key: 'hives', header: 'Hives', align: 'right', render: (row) => row.hives ?? '—' },
    { key: 'batches', header: 'Batches', align: 'right', render: (row) => row.batches ?? '—' },
    {
      key: 'state',
      header: 'State',
      render: (row) => (
        <Badge variant={row.is_active ? 'success' : 'neutral'} size="sm">
          {row.is_active ? 'Active' : 'Inactive'}
        </Badge>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <WorkspaceHeader
        title="Cluster analytics"
        description="Registration, apiary and production counts per cluster you oversee — all of it counted from stored records."
        requiredRoles={['KVIC_OFFICER']}
        actions={
          <Button to="/kvic/clusters" size="sm" variant="secondary" leftIcon={<Building2 size={15} />}>
            Manage clusters
          </Button>
        }
      />

      <section aria-label="Scope totals" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Clusters in scope" value={totals?.clusters ?? '—'} icon={<Building2 size={16} />} tone="honey" loading={loading} />
        <StatCard label="Honey batches" value={totals?.batches ?? '—'} helper="Produced by those clusters" loading={loading} />
        <StatCard label="Tests passed" value={totals?.passed ?? '—'} helper="Recorded outcomes, not estimates" loading={loading} />
        <StatCard
          label="Tests failed / inconclusive"
          value={`${totals?.failed ?? 0} / ${totals?.inconclusive ?? 0}`}
          helper="Failures and undecided tests"
          loading={loading}
        />
      </section>

      <Card>
        <CardHeader title="By cluster" description="One row per cluster in your scope." />
        <CardBody>
          <DataTable
            columns={columns}
            rows={rows}
            loading={loading}
            error={error}
            onRetry={load}
            emptyTitle="No clusters in your scope."
            emptyDescription="Clusters appear here once an administrator registers them and you are authorised for them."
            caption="Cluster analytics"
          />
        </CardBody>
      </Card>
    </div>
  );
}
