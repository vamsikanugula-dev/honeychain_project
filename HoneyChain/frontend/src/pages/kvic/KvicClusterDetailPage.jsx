import { useParams } from 'react-router-dom';

import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { Button } from '@/components/ui/Button';
import { ClusterView } from '@/components/clusters/ClusterView';

/**
 * KVIC officer view of one cluster: its members' hives, devices, telemetry and
 * analyses, read through the organisational relationship.
 */
export default function KvicClusterDetailPage() {
  const { clusterId } = useParams();

  return (
    <div className="space-y-6">
      <Breadcrumb
        items={[
          { label: 'KVIC', to: '/kvic' },
          { label: 'Clusters', to: '/kvic/clusters' },
          { label: 'Cluster' },
        ]}
      />
      <PageHeader
        title="Cluster"
        description="Who is in this cluster and what their apiaries are reporting. Read-only: records are corrected where they live."
        actions={
          <Button to="/kvic/hives" variant="secondary" size="sm">
            Hive registry
          </Button>
        }
      />
      <ClusterView
        clusterId={clusterId}
        hiveDetailBasePath="/kvic/hives"
        membersPath="/kvic/clusters"
        collectionsPath="/kvic/collections"
        batchesPath="/kvic/batches"
      />
    </div>
  );
}
