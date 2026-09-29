import { useEffect, useState } from 'react';
import { Link2, RefreshCw, ShieldCheck, TriangleAlert } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import * as blockchainService from '@/services/blockchainService';
import { normaliseError } from '@/utils/errors';
import { formatDateTime } from '@/utils/format';

const STATUS_STYLE = {
  CONFIRMED: 'success',
  PENDING: 'warning',
  SUBMITTED: 'info',
  FAILED: 'danger',
};

/** The batch view reads one backend-composed timeline, never the global ledger. */
export function BlockchainTraceability({ batchId }) {
  const [trace, setTrace] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setTrace(await blockchainService.getBatchTraceability(batchId));
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [batchId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <LoadingState message="Loading blockchain traceability..." />;
  if (error) return <ErrorState error={error} onRetry={load} />;
  const entries = trace?.blockchain?.transactions || [];

  return (
    <Card>
      <CardHeader
        title="Blockchain traceability"
        description="Only completed HoneyChain actions appear here. Fabric transaction IDs are shown when synchronization is confirmed."
        icon={<ShieldCheck size={18} aria-hidden="true" />}
        action={<Button variant="ghost" size="sm" onClick={load} leftIcon={<RefreshCw size={14} />}>Refresh</Button>}
      />
      <CardBody className="space-y-3">
        {!entries.length ? (
          <Alert variant="info" icon={<Link2 size={16} />}>
            No blockchain event has been recorded for this batch yet.
          </Alert>
        ) : (
          <ol className="space-y-3 border-l-2 border-sand-200 pl-4">
            {entries.map((entry) => (
              <li key={entry.event_id || entry.tx_id} className="relative rounded-lg border border-sand-200 bg-white p-3">
                <span className="absolute -left-[23px] top-5 h-3 w-3 rounded-full bg-forest-600 ring-4 ring-sand-50" />
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-mono text-sm font-semibold text-forest-800">{entry.tx_type}</p>
                    <p className="mt-1 text-xs text-ink-muted">{entry.timestamp ? formatDateTime(entry.timestamp) : 'Pending synchronization'}</p>
                  </div>
                  <Badge variant={STATUS_STYLE[entry.blockchain_status] || 'neutral'}>{entry.blockchain_status}</Badge>
                </div>
                {entry.tx_id ? <p className="mt-2 break-all font-mono text-xs text-ink-soft">Transaction: {entry.tx_id}</p> : null}
                {entry.last_error ? <p className="mt-2 text-xs text-status-danger">Synchronization error: {entry.last_error}</p> : null}
              </li>
            ))}
          </ol>
        )}
        {entries.some((entry) => entry.blockchain_status === 'PENDING' || entry.blockchain_status === 'FAILED') ? (
          <Alert variant="warning" icon={<TriangleAlert size={16} />}>
            The operational record is saved. One or more ledger events are awaiting synchronization and are not marked verified.
          </Alert>
        ) : null}
      </CardBody>
    </Card>
  );
}

export default BlockchainTraceability;
