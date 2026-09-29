import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { CheckCircle2, CircleDashed, PackageSearch, ShieldCheck } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import { Logo } from '@/components/common/Logo';
import * as blockchainService from '@/services/blockchainService';
import { normaliseError } from '@/utils/errors';
import { formatDate, formatDateTime } from '@/utils/format';

const EVENT_LABELS = {
  COLLECTION_COMPLETED: 'Collection completed', BATCH_CREATED: 'Batch created', PROCESSING_STARTED: 'Processing started', PROCESSING_COMPLETED: 'Processing completed', LAB_TEST_STARTED: 'Laboratory test started', QUALITY_CHECKED: 'Laboratory checked', QUALITY_FAILED: 'Quality failed', QUALITY_HOLD: 'Quality hold', PROCEEDED_WITH_RISK: 'Proceeded with risk', PACKAGING_STARTED: 'Packaging started', PACKAGE_CREATED: 'Package created', PACKAGED: 'Packaged', DISTRIBUTION_CREATED: 'Distribution created', DISTRIBUTION_DISPATCHED: 'Dispatched', IN_TRANSIT: 'In transit', DELIVERED: 'Delivered', RETAILER_RECEIVED: 'Retailer received', QR_GENERATED: 'QR generated',
};

export default function CustomerTraceabilityPage() {
  const { token } = useParams();
  const [trace, setTrace] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true); setError(null);
    try { setTrace(await blockchainService.getPublicTraceability(token)); }
    catch (caught) { setError(normaliseError(caught)); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <div className="mx-auto max-w-3xl p-8"><LoadingState message="Resolving package traceability..." /></div>;
  if (error) return <div className="mx-auto max-w-3xl p-8"><ErrorState error={error} onRetry={load} /></div>;
  if (!trace) return null;
  const product = trace.product || {};
  const source = trace.source || {};
  const ledger = trace.blockchain?.transactions || [];

  return (
    <main className="min-h-screen bg-sand-50">
      <header className="border-b border-sand-200 bg-white"><div className="mx-auto flex max-w-4xl items-center justify-between px-5 py-4"><Logo to="/" size={30} /><Link className="text-sm text-forest-700 hover:underline" to="/">HoneyChain</Link></div></header>
      <div className="mx-auto max-w-4xl space-y-6 px-5 py-8">
        <section><p className="text-xs font-semibold uppercase tracking-[0.18em] text-honey-700">HoneyChain traceability</p><h1 className="mt-2 text-3xl font-bold text-forest-950">Your honey&apos;s recorded journey</h1><p className="mt-2 text-sm text-ink-muted">This view uses a package QR resolver and never exposes account credentials, private notes or raw hive telemetry.</p></section>
        <Card><CardHeader title="Product" icon={<PackageSearch size={18} />} /><CardBody className="grid gap-4 sm:grid-cols-3"><div><p className="text-xs text-ink-muted">Batch</p><p className="font-mono font-semibold">{product.batch_id}</p></div><div><p className="text-xs text-ink-muted">Package</p><p className="font-mono font-semibold">{product.package_id}</p></div><div><p className="text-xs text-ink-muted">Package size</p><p className="font-semibold">{product.package_size} {product.unit}</p></div></CardBody></Card>
        <div className="grid gap-6 md:grid-cols-2">
          <Card><CardHeader title="Source" /><CardBody className="space-y-2 text-sm"><p><span className="text-ink-muted">Cluster: </span>{source.cluster || 'Not recorded'}</p><p><span className="text-ink-muted">Beekeeper reference: </span>{source.beekeeper_id || 'Not recorded'}</p><p><span className="text-ink-muted">Source hives: </span>{source.hives?.join(', ') || 'Not recorded'}</p><p><span className="text-ink-muted">Collection date: </span>{source.collection_date ? formatDate(source.collection_date) : 'Not recorded'}</p><p><span className="text-ink-muted">Actual collected: </span>{source.actual_collected_quantity} {source.unit}</p></CardBody></Card>
          <Card><CardHeader title="Processing" /><CardBody className="space-y-2 text-sm">{trace.processing ? <><p><span className="text-ink-muted">Type: </span>{trace.processing.type}</p><p><span className="text-ink-muted">Facility: </span>{trace.processing.facility || 'Not recorded'}</p><p><span className="text-ink-muted">Completed: </span>{trace.processing.completed_at ? formatDateTime(trace.processing.completed_at) : 'Not recorded'}</p></> : <p className="text-ink-muted">No processing completion is recorded yet.</p>}</CardBody></Card>
          <Card><CardHeader title="Laboratory" /><CardBody className="space-y-2 text-sm">{trace.laboratory ? <><p>Result: <Badge variant={trace.laboratory.result === 'PASS' ? 'success' : trace.laboratory.result === 'FAIL' ? 'danger' : 'warning'}>{trace.laboratory.result}</Badge></p><p className="text-ink-muted">{trace.laboratory.summary}</p>{trace.laboratory.measurements?.map((item) => <p key={item.name}>{item.name}: {item.value} {item.unit} ({item.status})</p>)}</> : <p className="text-ink-muted">No laboratory result is recorded yet.</p>}</CardBody></Card>
          <Card><CardHeader title="Packaging" /><CardBody className="space-y-2 text-sm"><p><span className="text-ink-muted">Package identity: </span><span className="font-mono">{trace.packaging?.package_identity}</span></p><p><span className="text-ink-muted">Packaging unit: </span>{trace.packaging?.packaging_unit || 'Not recorded'}</p><p><span className="text-ink-muted">Container: </span>{product.packaging_type || 'Not recorded'}</p></CardBody></Card>
        </div>
        <Card><CardHeader title="Distribution" /><CardBody>{trace.distribution?.length ? <ul className="space-y-3">{trace.distribution.map((shipment, index) => <li key={`${shipment.status}-${index}`} className="rounded-lg border border-sand-200 p-3 text-sm"><Badge variant="info">{shipment.status}</Badge><p className="mt-2 text-ink-muted">Dispatched {shipment.dispatched_at ? formatDateTime(shipment.dispatched_at) : '—'} · In transit {shipment.in_transit_at ? formatDateTime(shipment.in_transit_at) : '—'} · Delivered {shipment.delivered_at ? formatDateTime(shipment.delivered_at) : '—'}{shipment.retailer_received_at ? ` · Retailer received ${formatDateTime(shipment.retailer_received_at)}` : ''}</p></li>)}</ul> : <p className="text-sm text-ink-muted">No distribution event is recorded yet.</p>}</CardBody></Card>
        <Card><CardHeader title="Blockchain ledger" description="Chronological immutable event history from the relevant package batch." icon={<ShieldCheck size={18} />} /><CardBody>{ledger.length ? <ol className="space-y-3 border-l-2 border-sand-200 pl-4">{ledger.map((event, index) => <li key={`${event.tx_id || event.type}-${index}`} className="relative text-sm"><span className="absolute -left-[22px] top-1 h-3 w-3 rounded-full bg-forest-600 ring-4 ring-sand-50" /> <div className="flex flex-wrap items-center gap-2"><strong>{EVENT_LABELS[event.type] || event.type}</strong><Badge variant={event.status === 'CONFIRMED' ? 'success' : 'warning'} size="sm">{event.status}</Badge></div><p className="text-xs text-ink-muted">{event.timestamp ? formatDateTime(event.timestamp) : 'Pending synchronization'}{event.tx_id ? ` · ${event.tx_id}` : ''}</p></li>)}</ol> : <Alert variant="info" icon={<CircleDashed size={16} />}>No blockchain event has been synchronized for this package batch yet.</Alert>}</CardBody></Card>
        {trace.blockchain?.synchronized ? <Alert variant="success" icon={<CheckCircle2 size={16} />}>All available events on this trace are confirmed by the blockchain service.</Alert> : <Alert variant="warning">Some operational events are still awaiting blockchain synchronization.</Alert>}
      </div>
    </main>
  );
}
