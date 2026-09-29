import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable } from '@/components/common/DataTable';
import { formatDate, formatNumber } from '@/utils/format';

/**
 * The packaging worklist: batches the laboratory approved, with what is left to pack.
 *
 * Every figure is read from the batch's own records — the collection quantity from
 * the harvest, the approved quantity from the completed processing run, what is
 * already packaged from the completed packaging runs, and the remainder as the
 * difference. The table computes nothing and offers no quantity it could not stand
 * behind: "Pack" is offered only while there is honey left to pack.
 *
 * A batch with no remaining quantity stays visible in history rather than vanishing,
 * so a partly packed batch is never mistaken for an empty one.
 */
export function ApprovedBatchTable({
  batches = [],
  loading = false,
  error = null,
  onRetry,
  meta,
  onPageChange,
  canWrite = false,
  onPack = null,
  onOpenBatch = null,
  busyId = null,
  emptyTitle = 'No approved batch is waiting to be packed.',
  emptyDescription = 'A batch appears here once the laboratory approves it.',
}) {
  const columns = [
    {
      key: 'batch_code',
      header: 'Batch',
      render: (row) => (
        <span className="flex flex-col gap-1">
          <button
            type="button"
            className="text-left font-mono text-sm font-medium text-forest-700 underline decoration-honey-400 decoration-2 underline-offset-2"
            onClick={() => onOpenBatch?.(row)}
          >
            {row.batch_code}
          </button>
          {row.collection_code ? (
            <span className="font-mono text-xs text-ink-muted">{row.collection_code}</span>
          ) : null}
          {row.collection_date ? (
            <span className="text-xs text-ink-muted">Harvested {formatDate(row.collection_date)}</span>
          ) : null}
        </span>
      ),
    },
    {
      key: 'beekeeper',
      header: 'Beekeeper',
      render: (row) => (
        <span className="flex flex-col gap-1 text-xs">
          <span className="text-sm text-ink-soft">{row.beekeeper_name || 'Beekeeper'}</span>
          <span className="font-mono text-ink-muted">{row.beekeeper_code || '—'}</span>
          {row.cluster_name ? (
            <span className="text-ink-muted">{row.cluster_name}</span>
          ) : (
            <span className="text-ink-muted">Not in a cluster</span>
          )}
        </span>
      ),
    },
    {
      key: 'quantities',
      header: 'Quantities',
      render: (row) => (
        <span className="flex flex-col gap-1 text-xs">
          <span className="text-ink-soft">
            Collected {formatNumber(row.collection_quantity)} {row.unit_label || ''}
          </span>
          {row.processing_code ? (
            <span className="text-ink-muted">
              Processing output {formatNumber(row.processing_output_quantity)}
            </span>
          ) : null}
          <span className="font-medium text-ink">
            Approved {formatNumber(row.approved_quantity)}
          </span>
        </span>
      ),
    },
    {
      key: 'laboratory',
      header: 'Laboratory',
      render: (row) => (
        <span className="flex flex-col gap-1 text-xs">
          {row.laboratory_test_code ? (
            <span className="font-mono text-ink-soft">{row.laboratory_test_code}</span>
          ) : null}
          <Badge variant={row.laboratory_result === 'PASS' ? 'success' : 'info'} size="sm">
            {row.laboratory_result_label || row.laboratory_result || 'Approved'}
          </Badge>
        </span>
      ),
    },
    {
      key: 'packed',
      header: 'Packaged',
      align: 'right',
      render: (row) => (
        <span className="flex flex-col gap-1">
          <span className="text-sm text-ink">
            {formatNumber(row.packaged_quantity)} {row.unit_label || ''}
          </span>
          <span className="text-xs text-ink-muted">{row.package_count} package(s)</span>
        </span>
      ),
    },
    {
      key: 'remaining',
      header: 'Remaining',
      align: 'right',
      render: (row) => (
        <span className="flex flex-col gap-1">
          <span className="text-sm font-medium text-ink">
            {formatNumber(row.remaining_quantity)} {row.unit_label || ''}
          </span>
          <span className="text-xs text-ink-muted">
            {Number(row.remaining_quantity) > 0 ? 'Available to pack' : 'Fully packed'}
          </span>
        </span>
      ),
    },
    {
      key: 'packaging_status',
      header: 'Packaging',
      render: (row) => (
        <span className="flex flex-col gap-1">
          <Badge
            size="sm"
            variant={
              row.packaging_status === 'COMPLETED'
                ? 'success'
                : row.packaging_status === 'IN_PROGRESS'
                  ? 'warning'
                  : row.packaging_status === 'CANCELLED'
                    ? 'neutral'
                    : 'pending'
            }
          >
            {row.packaging_status_label || row.packaging_status || 'Not started'}
          </Badge>
          {row.remaining_quantity && Number(row.remaining_quantity) === 0 ? (
            <span className="text-xs text-ink-muted">Nothing left to pack</span>
          ) : null}
        </span>
      ),
    },
    {
      key: 'actions',
      header: 'Actions',
      render: (row) => {
        if (!canWrite) {
          return <span className="text-xs text-ink-muted">Read-only</span>;
        }
        const remaining = Number(row.remaining_quantity || 0);
        if (remaining <= 0) {
          return <span className="text-xs text-ink-muted">Fully packed</span>;
        }
        return (
          <Button
            size="sm"
            disabled={busyId === row.batch_id}
            onClick={() => onPack?.(row)}
            data-testid={`pack-batch-${row.batch_code}`}
          >
            Pack this batch
          </Button>
        );
      },
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={batches}
      rowKey={(row) => row.batch_id}
      loading={loading}
      error={error}
      onRetry={onRetry}
      meta={meta}
      onPageChange={onPageChange}
      emptyTitle={emptyTitle}
      emptyDescription={emptyDescription}
      caption="Batches approved by the laboratory and awaiting packaging"
    />
  );
}

export default ApprovedBatchTable;
