import { useEffect, useState } from 'react';
import { Database, RefreshCw, RotateCw, Search, WifiOff } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { DataTable } from '@/components/common/DataTable';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import { WorkspaceHeader } from '@/components/common/WorkspaceHeader';
import * as blockchainService from '@/services/blockchainService';
import { normaliseError } from '@/utils/errors';
import { formatDateTime } from '@/utils/format';

const STATUS_VARIANT = { CONFIRMED: 'success', PENDING: 'warning', SUBMITTED: 'info', FAILED: 'danger' };

/** One real-ledger screen shared by admin and KVIC; backend supplies the scope. */
export default function BlockchainLedgerPage({ kvic = false }) {
  const [ledger, setLedger] = useState(null);
  const [health, setHealth] = useState(null);
  const [filters, setFilters] = useState({ search: '', txType: '', status: '' });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [retrying, setRetrying] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [entries, status] = await Promise.all([
        blockchainService.listTransactions(filters),
        blockchainService.getBlockchainHealth(),
      ]);
      setLedger(entries);
      setHealth(status);
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const retry = async (eventId) => {
    setRetrying(eventId);
    try {
      await blockchainService.retrySynchronization(eventId);
      await load();
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setRetrying(null);
    }
  };

  const transactions = ledger?.transactions || [];
  const columns = [
    { key: 'tx_type', header: 'Type', render: (row) => <span className="font-mono text-xs font-semibold">{row.tx_type}</span> },
    { key: 'batch_id', header: 'Batch / package', render: (row) => <span className="font-mono text-xs">{row.batch_id}</span> },
    { key: 'tx_id', header: 'Transaction ID', render: (row) => row.tx_id ? <span className="block max-w-[180px] truncate font-mono text-xs">{row.tx_id}</span> : <span className="text-xs text-ink-muted">Awaiting Fabric</span> },
    { key: 'timestamp', header: 'Recorded', render: (row) => row.timestamp ? formatDateTime(row.timestamp) : '—' },
    { key: 'blockchain_status', header: 'Sync', render: (row) => <Badge variant={STATUS_VARIANT[row.blockchain_status] || 'neutral'} size="sm">{row.blockchain_status}</Badge> },
    { key: 'detail', header: '', align: 'right', render: (row) => <Button variant="ghost" size="sm" onClick={() => setSelected(row)}>Details</Button> },
  ];

  if (loading) return <LoadingState message="Loading real blockchain ledger..." />;
  if (error && !ledger) return <ErrorState error={error} onRetry={load} />;

  return (
    <div className="space-y-6">
      <WorkspaceHeader
        eyebrow={kvic ? 'KVIC traceability' : 'Administration'}
        title={kvic ? 'Authorised blockchain traceability' : 'Blockchain ledger'}
        description={kvic ? 'Real Fabric events only for batches in your authorised cluster scope.' : 'Real Fabric transactions, legacy ledger records and HoneyChain synchronization state.'}
        actions={<Button variant="secondary" size="sm" onClick={load} leftIcon={<RefreshCw size={15} />}>Refresh ledger</Button>}
      />

      {ledger?.remote_ledger_error ? <Alert variant="warning" icon={<WifiOff size={16} />}>Fabric ledger is currently unavailable: {ledger.remote_ledger_error}. Local pending/failed sync records remain visible.</Alert> : null}
      {error ? <Alert variant="danger">{error.message}</Alert> : null}

      <section className="grid gap-4 md:grid-cols-4">
        <Card><CardBody><p className="text-sm text-ink-muted">Fabric service</p><p className="mt-1 font-semibold text-ink">{health?.service || 'Unknown'}</p></CardBody></Card>
        <Card><CardBody><p className="text-sm text-ink-muted">Pending sync</p><p className="mt-1 text-2xl font-semibold text-honey-700">{health?.pending ?? '—'}</p></CardBody></Card>
        <Card><CardBody><p className="text-sm text-ink-muted">Failed sync</p><p className="mt-1 text-2xl font-semibold text-status-danger">{health?.failed ?? '—'}</p></CardBody></Card>
        <Card><CardBody><p className="text-sm text-ink-muted">Last successful transaction</p><p className="mt-1 text-sm font-medium text-ink">{health?.last_successful_transaction_at ? formatDateTime(health.last_successful_transaction_at) : '—'}</p></CardBody></Card>
      </section>

      <Card>
        <CardHeader title="Transactions" description="Fabric is the immutable ledger; PENDING and FAILED entries are durable HoneyChain outbox events, not confirmations." icon={<Database size={18} />} />
        <CardBody className="space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            <Input label="Search" name="ledger-search" value={filters.search} onChange={(event) => setFilters((f) => ({ ...f, search: event.target.value }))} placeholder="Transaction, batch or package" />
            <label><span className="hc-label">Event type</span><input className="h-11 w-full rounded-lg border border-sand-300 px-3 text-sm" value={filters.txType} onChange={(event) => setFilters((f) => ({ ...f, txType: event.target.value }))} placeholder="e.g. PACKAGED" /></label>
            <label><span className="hc-label">Sync status</span><select className="h-11 w-full rounded-lg border border-sand-300 px-3 text-sm" value={filters.status} onChange={(event) => setFilters((f) => ({ ...f, status: event.target.value }))}><option value="">Select sync status</option><option>CONFIRMED</option><option>PENDING</option><option>SUBMITTED</option><option>FAILED</option></select></label>
            <div className="flex items-end"><Button onClick={load} leftIcon={<Search size={15} />}>Apply filters</Button></div>
          </div>
          <DataTable columns={columns} rows={transactions} emptyTitle="No matching transactions" emptyDescription="No real Fabric or local synchronization record matches these filters." />
        </CardBody>
      </Card>

      {selected ? (
        <Card>
          <CardHeader title="Transaction details" description="Raw payload is shown for authorised technical review." action={<Button variant="ghost" size="sm" onClick={() => setSelected(null)}>Close</Button>} />
          <CardBody className="space-y-3">
            <dl className="grid gap-2 text-sm sm:grid-cols-2"><div><dt className="text-ink-muted">Transaction ID</dt><dd className="break-all font-mono">{selected.tx_id || 'Awaiting Fabric'}</dd></div><div><dt className="text-ink-muted">Type</dt><dd>{selected.tx_type}</dd></div><div><dt className="text-ink-muted">Batch</dt><dd className="font-mono">{selected.batch_id}</dd></div><div><dt className="text-ink-muted">Status</dt><dd>{selected.blockchain_status}</dd></div></dl>
            {selected.linked_record ? <p className="text-sm text-ink-muted">Linked HoneyChain record: <span className="font-mono">{selected.linked_record.type} / {selected.linked_record.id}</span></p> : null}
            <pre className="max-h-80 overflow-auto rounded-lg bg-ink p-4 text-xs text-sand-100">{JSON.stringify(selected.payload, null, 2)}</pre>
            {['FAILED', 'PENDING', 'SUBMITTED'].includes(selected.blockchain_status) ? <Button loading={retrying === selected.event_id} onClick={() => retry(selected.event_id)} leftIcon={<RotateCw size={15} />}>Retry synchronization</Button> : null}
          </CardBody>
        </Card>
      ) : null}
    </div>
  );
}
