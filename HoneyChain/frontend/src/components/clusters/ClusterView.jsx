import { useCallback, useEffect, useState } from 'react';
import { Building2, RefreshCw, UserCog } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import { ClusterOverviewCards } from '@/components/clusters/ClusterOverviewCards';
import { ClusterHivesTable } from '@/components/clusters/ClusterHivesTable';
import { ClusterDevicesTable } from '@/components/clusters/ClusterDevicesTable';
import { ClusterHarvestPanel } from '@/components/clusters/ClusterHarvestPanel';
import { ClusterAiPanel } from '@/components/clusters/ClusterAiPanel';
import { ClusterTelemetryPanel } from '@/components/clusters/ClusterTelemetryPanel';
import { normaliseError } from '@/utils/errors';
import { formatDateTime } from '@/utils/format';
import * as clusterAnalytics from '@/services/clusterAnalyticsService';

const VERIFICATION_VARIANT = {
  VERIFIED: 'success',
  PENDING: 'pending',
  UNDER_REVIEW: 'info',
  REJECTED: 'danger',
  SUSPENDED: 'warning',
};

/**
 * One cluster, seen as a view over the records that already exist.
 *
 * The chain is `KVIC → cluster → beekeeper → hive → device → telemetry →
 * analysis`, and this screen follows it without copying anything: the hives are
 * the owners' rows, the devices are paired to those hives, the readings were
 * stored against those devices and the assessments were computed from those
 * readings. Editing anything is done where the record lives — here the officer
 * reads, and follows a hive into its own screen when a closer look is needed.
 *
 * Every panel distinguishes "none" from "not loaded": counters show real zeroes,
 * and an empty list says so in words.
 */
export function ClusterView({
  clusterId,
  hiveDetailBasePath,
  membersPath,
  collectionsPath = null,
  batchesPath = null,
}) {
  const [overview, setOverview] = useState(null);
  const [aiState, setAiState] = useState(null);
  const [telemetry, setTelemetry] = useState(null);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(
    async ({ silent = false } = {}) => {
      if (silent) setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        // Three independent reads; the cluster view is composed from the same
        // records the rest of the platform serves.
        const [counters, ai, latest] = await Promise.all([
          clusterAnalytics.getClusterOverview(clusterId),
          clusterAnalytics.getClusterAiState(clusterId),
          clusterAnalytics.getClusterLatestTelemetry(clusterId),
        ]);
        setOverview(counters);
        setAiState(ai);
        setTelemetry(latest);
      } catch (caught) {
        setError(normaliseError(caught));
        setOverview(null);
        setAiState(null);
        setTelemetry(null);
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [clusterId],
  );

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !overview) {
    return <LoadingState message="Loading the cluster…" />;
  }

  if (error && !overview) {
    return <ErrorState error={error} onRetry={() => load()} />;
  }

  const cluster = overview?.cluster;
  const beekeepers = overview?.beekeepers;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          icon={<Building2 size={18} aria-hidden="true" />}
          title={cluster?.cluster_name || 'Cluster'}
          description={
            <>
              {cluster?.cluster_code ? <span className="font-medium text-ink-soft">{cluster.cluster_code} · </span> : null}
              {[cluster?.district, cluster?.state].filter(Boolean).join(', ') || 'District not recorded'}
            </>
          }
          action={
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={cluster?.is_active ? 'success' : 'neutral'} size="sm">
                {cluster?.is_active ? 'Active' : 'Inactive'}
              </Badge>
              {membersPath ? (
                <Button to={membersPath} variant="secondary" size="sm" leftIcon={<UserCog size={16} aria-hidden="true" />}>
                  Beekeepers
                </Button>
              ) : null}
              <Button
                variant="ghost"
                size="sm"
                loading={refreshing}
                onClick={() => load({ silent: true })}
                leftIcon={<RefreshCw size={16} aria-hidden="true" />}
              >
                Refresh
              </Button>
            </div>
          }
        />
        <CardBody className="space-y-4">
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-xs uppercase tracking-wide text-ink-muted">Coordinator</dt>
              <dd className="text-ink">{cluster?.coordinator_name || 'Not recorded'}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-ink-muted">Coordinator phone</dt>
              <dd className="text-ink">{cluster?.coordinator_phone || 'Not recorded'}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-ink-muted">Membership</dt>
              <dd className="text-ink">
                {beekeepers?.total ?? 0} beekeeper(s)
                {beekeepers?.by_verification_status ? (
                  <span className="ml-2 inline-flex flex-wrap gap-1">
                    {Object.entries(beekeepers.by_verification_status)
                      .filter(([, value]) => value > 0)
                      .map(([status, value]) => (
                        <Badge key={status} variant={VERIFICATION_VARIANT[status] || 'neutral'} size="sm">
                          {value} {status.replaceAll('_', ' ').toLowerCase()}
                        </Badge>
                      ))}
                  </span>
                ) : null}
              </dd>
            </div>
          </dl>

          {overview?.generated_at ? (
            <p className="text-xs text-ink-muted">
              Counted at {formatDateTime(overview.generated_at)}. Every figure is a query over the
              beekeepers&apos; own records.
            </p>
          ) : null}

          {!cluster?.is_active ? (
            <Alert variant="info" title="This cluster is inactive">
              It stays readable, but no beekeeper or hive can be placed in it until it is reactivated.
            </Alert>
          ) : null}
        </CardBody>
      </Card>

      <ClusterOverviewCards overview={overview} loading={loading} />

      <div className="grid gap-5 lg:grid-cols-2">
        <ClusterTelemetryPanel telemetry={telemetry} loading={loading} />
        <Card>
          <CardHeader
            title="What this view is"
            description="How the records on this page are connected."
          />
          <CardBody className="space-y-3 text-sm text-ink-soft">
            <p>
              The cluster holds the beekeepers. Each beekeeper holds their own hives. Each hive holds
              its devices, the devices hold the readings, and the assessments are computed from
              those readings.
            </p>
            <p>
              This screen reads that chain from the top. It stores nothing of its own, so a hive
              corrected on its own screen — or a beekeeper moved to another cluster — is reflected
              here immediately.
            </p>
            <p className="text-ink-muted">
              Hives whose owner is not in any cluster are not shown here. Officers resolve them
              through the hive registry filter <code>has_cluster=false</code> and place them
              individually.
            </p>
          </CardBody>
        </Card>
      </div>

      <ClusterHivesTable
        clusterId={clusterId}
        hiveDetailBasePath={hiveDetailBasePath}
        onLoaded={() => {}}
      />

      <ClusterAiPanel aiState={aiState} loading={loading} />

      <ClusterDevicesTable clusterId={clusterId} />

      <ClusterHarvestPanel
        clusterId={clusterId}
        collectionsPath={collectionsPath}
        batchesPath={batchesPath}
      />

      <p className="text-xs text-ink-muted">
        Looking for a beekeeper list? Membership is managed on{' '}
        <Link className="underline" to={membersPath || '#'}>
          the cluster management screen
        </Link>
        .
      </p>
    </div>
  );
}

export default ClusterView;
