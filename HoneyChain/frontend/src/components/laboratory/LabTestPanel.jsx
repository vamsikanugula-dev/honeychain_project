import { useCallback, useEffect, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  FlaskConical,
  Info,
  Pencil,
  Plus,
  ShieldAlert,
  Trash2,
} from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { ROLES } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';
import * as adminService from '@/services/adminService';
import { AssignmentDialog } from '@/components/common/AssignmentDialog';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import {
  LAB_MESSAGES,
  LAB_PARAMETER_STATUS_META,
  LAB_RESULT_META,
  LAB_TEST_STATUS_META,
  measurementText,
  referenceText,
} from '@/constants/laboratory';
import * as laboratoryService from '@/services/laboratoryService';
import { normaliseError } from '@/utils/errors';
import { formatDate, formatDateTime } from '@/utils/format';

/**
 * One laboratory test.
 *
 * The panel records measurements and then asks the platform for a decision. It
 * never offers the verdict as a choice: `Complete test` sends the remarks and the
 * server computes PASS, FAIL or INCONCLUSIVE from the recorded values and the
 * configured ranges, explaining itself in `evaluation_notes`. The single
 * exception — an authorised override — is an administrator-only dialog that
 * demands a reason and is written to the audit log.
 *
 * While the test is open every recorded value can be corrected or removed, and the
 * correction is logged with the value it replaced. Once the test is completed the
 * panel becomes a record: no edit controls, and a retest is the way forward.
 */

function Row({ label, children }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 py-1.5">
      <dt className="text-sm text-ink-muted">{label}</dt>
      <dd className="text-sm font-medium text-ink">{children}</dd>
    </div>
  );
}

export function LabTestPanel({ testId, canWrite = false, canOverride = false, onChanged = null }) {
  const { user } = useAuth();
  const [assignOpen, setAssignOpen] = useState(false);
  const [technicians, setTechnicians] = useState([]);
  const [techniciansLoading, setTechniciansLoading] = useState(false);
  const [techniciansError, setTechniciansError] = useState(null);
  const [test, setTest] = useState(null);
  const [parameters, setParameters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [resultForm, setResultForm] = useState({ open: false, code: '', value: '', method: '', remarks: '' });
  const [editingResult, setEditingResult] = useState(null);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [override, setOverride] = useState({ result: 'PASS', reason: '' });
  const [completeOpen, setCompleteOpen] = useState(false);
  const [completeRemarks, setCompleteRemarks] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [payload, catalogue] = await Promise.all([
        laboratoryService.getTest(testId),
        laboratoryService.listParameters().catch(() => []),
      ]);
      setTest(payload);
      setParameters(catalogue);
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [testId]);

  useEffect(() => {
    load();
  }, [load]);

  // Who may take this sample is the server's answer: an administrator reads the
  // active technician accounts the platform holds; a technician may only name
  // themselves, which the dialog offers as a single button.
  const openAssign = async () => {
    setAssignOpen(true);
    setActionError(null);
    if (user?.role !== ROLES.ADMIN) return;
    setTechniciansLoading(true);
    setTechniciansError(null);
    try {
      const { users } = await adminService.listUsers({ role: ROLES.LAB_TECHNICIAN, pageSize: 100 });
      setTechnicians(users);
    } catch (caught) {
      setTechniciansError(normaliseError(caught));
    } finally {
      setTechniciansLoading(false);
    }
  };

  const act = async (operation) => {
    setBusy(true);
    setActionError(null);
    try {
      await operation();
      await load();
      if (onChanged) onChanged();
    } catch (caught) {
      setActionError(normaliseError(caught));
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <LoadingState message={LAB_MESSAGES.loadingLaboratory} />;
  if (error) return <ErrorState error={error} onRetry={load} />;
  if (!test) return null;

  const statusMeta = LAB_TEST_STATUS_META[test.status] || LAB_TEST_STATUS_META.PENDING;
  const resultMeta = LAB_RESULT_META[test.overall_result] || LAB_RESULT_META.PENDING;
  const open = test.status !== 'COMPLETED';
  const recordedCodes = new Set(test.results.map((result) => result.parameter_code));
  const available = parameters.filter(
    (parameter) => parameter.is_active !== false && !recordedCodes.has(parameter.code),
  );
  const selectedParameter = parameters.find((parameter) => parameter.code === resultForm.code) || null;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title={`Laboratory test ${test.test_code}`}
          description={test.next_step || 'Record the measured values, then ask the platform to decide.'}
          icon={<FlaskConical size={18} aria-hidden="true" />}
          action={
            <span className="flex flex-wrap items-center gap-2">
              <Badge variant={statusMeta.variant} size="sm">
                {test.status_label || statusMeta.label}
              </Badge>
              <Badge variant={resultMeta.variant} size="sm">
                {test.overall_result_label || resultMeta.label}
              </Badge>
              {test.round_number > 1 || test.retest_of_id ? (
                <Badge variant="neutral" size="sm">
                  Round {test.round_number}
                </Badge>
              ) : null}
              {test.is_override ? (
                <Badge variant="warning" size="sm">
                  Overridden
                </Badge>
              ) : null}
            </span>
          }
        />
        <CardBody className="space-y-4">
          <dl className="divide-y divide-sand-100">
            <Row label="Sample">
              <span className="font-mono text-sm">{test.sample_code}</span>
              <span className="ml-2 text-xs text-ink-muted">
                {Number(test.sample_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })}{' '}
                {test.sample_unit_label}
                {test.sample_collected_at ? ` · taken ${formatDateTime(test.sample_collected_at)}` : ''}
              </span>
            </Row>
            <Row label="Laboratory">{test.laboratory_name || test.laboratory_code || '—'}</Row>
            <Row label="Technician">{test.technician_name || '—'}</Row>
            {/*
              Who is responsible for this sample, and whether they have taken it on.
              Allocating and accepting are two different facts: the sample is on the
              bench because somebody accepted it, not because it was allocated.
            */}
            <Row label="Assignment">
              {test.assigned_technician_id ? (
                <span className="flex flex-wrap items-center gap-2">
                  <Badge
                    variant={test.assignment_status === 'ACCEPTED' ? 'success' : 'neutral'}
                    size="sm"
                  >
                    {test.assignment_status === 'ACCEPTED' ? 'Accepted' : 'Assigned'}
                  </Badge>
                  <span>{test.assigned_technician_name || 'Named technician'}</span>
                  {test.assigned_at ? (
                    <span className="text-xs text-ink-muted">allocated {formatDateTime(test.assigned_at)}</span>
                  ) : null}
                  {canWrite && open ? (
                    <Button size="sm" variant="ghost" onClick={() => openAssign()}>
                      Re-allocate
                    </Button>
                  ) : null}
                </span>
              ) : (
                <span className="flex flex-wrap items-center gap-2">
                  <Badge variant="warning" size="sm">
                    Unassigned
                  </Badge>
                  <span className="text-xs text-ink-muted">Nobody is responsible for this sample</span>
                  {canWrite && open ? (
                    <Button size="sm" variant="secondary" onClick={() => openAssign()}>
                      Assign
                    </Button>
                  ) : null}
                </span>
              )}
            </Row>
            {test.accepted_at ? (
              <Row label="Accepted">{formatDateTime(test.accepted_at)}</Row>
            ) : null}
            {test.assigned_by_name && test.assignment_status === 'ASSIGNED' ? (
              <Row label="Allocated by">{test.assigned_by_name}</Row>
            ) : null}
            <Row label="Test date">{formatDate(test.test_date)}</Row>
            {test.completed_at ? <Row label="Completed">{formatDateTime(test.completed_at)}</Row> : null}
            {test.remarks ? <Row label="Remarks">{test.remarks}</Row> : null}
            {test.override_reason ? (
              <Row label="Override reason">
                <span className="text-ink-soft">{test.override_reason}</span>
                {test.decided_by_name ? (
                  <span className="ml-2 text-xs text-ink-muted">{test.decided_by_name}</span>
                ) : null}
              </Row>
            ) : null}
          </dl>

          {test.evaluation_notes?.length ? (
            <Alert variant={test.overall_result === 'FAIL' ? 'danger' : 'info'} icon={<Info size={16} aria-hidden="true" />}>
              <ul className="space-y-1">
                {test.evaluation_notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </Alert>
          ) : null}

          {actionError ? (
            <Alert variant="danger" icon={<AlertCircle size={16} aria-hidden="true" />}>
              {actionError.message}
            </Alert>
          ) : null}
        </CardBody>
      </Card>

      {/* The chain back to the apiary, from stored records */}
      <Card>
        <CardHeader
          title="Sample traceability"
          description="Batch → processing → collection → hives → beekeeper → cluster, read from the records themselves."
        />
        <CardBody>
          <ol className="space-y-3">
            {test.traceability.map((node) => (
              <li key={`${node.kind}-${node.identifier}`} className="flex gap-3">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-sand-300 bg-white text-xs font-semibold text-ink-soft">
                  {node.kind.slice(0, 2)}
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink">
                    {node.label}: <span className="font-mono">{node.identifier}</span>
                  </p>
                  <p className="text-xs text-ink-muted">
                    {node.detail || '—'}
                    {node.recorded_at ? ` · ${formatDateTime(node.recorded_at)}` : ''}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </CardBody>
      </Card>

      {/*
        Handing the sample to a named technician. A technician may only name
        themselves; an administrator allocates to the accounts the platform holds.
      */}
      <AssignmentDialog
        open={assignOpen}
        onClose={() => setAssignOpen(false)}
        title={`Assign ${test.test_code}`}
        description={`Sample ${test.sample_code}. The technician who accepts it is the one who measures it — the server records both facts separately.`}
        assigneeLabel="Laboratory technician"
        people={user?.role === ROLES.ADMIN ? technicians : []}
        peopleLoading={techniciansLoading}
        peopleError={techniciansError}
        currentAssigneeId={test.assigned_technician_id}
        selfOption={
          user?.role === ROLES.ADMIN || !user
            ? null
            : {
                id: user.id,
                label: 'Assign to me',
                helper: 'A technician can take an unallocated sample personally.',
              }
        }
        emptyHint="No laboratory technician account is available yet. An administrator creates one in Administration → Users."
        onAssign={async (technicianId) => {
          await act(() => laboratoryService.assignTest(test.id, technicianId));
        }}
      />

      {/* Measurements */}
      <Card>
        <CardHeader
          title="Measured values"
          description="Only what an instrument reported is stored here — no default, no expected value."
          action={
            canWrite && open ? (
              <span className="flex flex-wrap gap-2">
                {test.can_accept ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={busy}
                    onClick={() => act(() => laboratoryService.acceptTest(test.id))}
                    data-testid="accept-test"
                  >
                    Accept this sample
                  </Button>
                ) : null}
                <Button
                  size="sm"
                  leftIcon={<Plus size={15} />}
                  onClick={() => setResultForm({ open: true, code: '', value: '', method: '', remarks: '' })}
                >
                  Record a measurement
                </Button>
              </span>
            ) : null
          }
        />
        <CardBody className="space-y-4">
          {test.results.length ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-sand-200 text-sm" data-testid="lab-results">
                <thead className="bg-sand-100/70">
                  <tr>
                    {['Parameter', 'Measured', 'Configured range', 'Outcome', 'Method', ''].map((header) => (
                      <th
                        key={header}
                        scope="col"
                        className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-soft"
                      >
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-sand-100">
                  {test.results.map((result) => {
                    const status = LAB_PARAMETER_STATUS_META[result.status] || LAB_PARAMETER_STATUS_META.NOT_EVALUATED;
                    return (
                      <tr key={result.id} data-parameter={result.parameter_code}>
                        <td className="px-4 py-3">
                          <span className="font-medium text-ink">{result.parameter_name}</span>
                          <span className="ml-2 text-xs text-ink-muted">{result.parameter_code}</span>
                        </td>
                        <td className="px-4 py-3 text-ink">{measurementText(result)}</td>
                        <td className="px-4 py-3 text-sm text-ink-soft">
                          {referenceText(result) || <span className="text-ink-muted">No range configured</span>}
                          {result.reference_source ? (
                            <span className="ml-1 text-xs text-ink-muted">({result.reference_source})</span>
                          ) : null}
                        </td>
                        <td className="px-4 py-3">
                          <Badge variant={status.variant} size="sm">
                            {status.label}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-xs text-ink-muted">{result.method || '—'}</td>
                        <td className="px-4 py-3 text-right">
                          {canWrite && open ? (
                            <span className="flex justify-end gap-1">
                              <Button
                                size="sm"
                                variant="ghost"
                                aria-label={`Correct ${result.parameter_name}`}
                                onClick={() => setEditingResult(result)}
                              >
                                <Pencil size={14} />
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                aria-label={`Remove ${result.parameter_name}`}
                                loading={busy}
                                onClick={() => act(() => laboratoryService.deleteResult(test.id, result.id))}
                              >
                                <Trash2 size={14} />
                              </Button>
                            </span>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-ink-muted">{LAB_MESSAGES.resultsEmpty}</p>
          )}

          {test.missing_required_parameters?.length ? (
            <p className="text-xs text-ink-muted">
              Required and not yet recorded: {test.missing_required_parameters.join(', ')}. Until they
              are recorded, a completed test can only be inconclusive.
            </p>
          ) : null}

          <div className="flex flex-wrap gap-2">
            {canWrite && open ? (
              <Button
                size="sm"
                leftIcon={<CheckCircle2 size={15} />}
                onClick={() => setCompleteOpen(true)}
                disabled={!test.results.length && !test.is_override}
                data-testid="complete-test"
              >
                Complete test
              </Button>
            ) : null}
            {canOverride ? (
              <Button
                size="sm"
                variant="secondary"
                leftIcon={<ShieldAlert size={15} />}
                onClick={() => setOverrideOpen(true)}
              >
                Override the outcome
              </Button>
            ) : null}
          </div>

          {!open ? (
            <p className="rounded-lg border border-sand-300 bg-sand-50 px-3 py-2 text-xs text-ink-soft">
              This test is closed. Its recorded values and its result are read, never rewritten. A
              retest opens a new round against the same batch and leaves this one exactly as it is.
            </p>
          ) : null}
        </CardBody>
      </Card>

      {/* Record a measurement */}
      <Modal
        open={resultForm.open}
        onClose={() => setResultForm({ open: false, code: '', value: '', method: '', remarks: '' })}
        title="Record a measured value"
        description="The number you enter is the number that is stored; the platform does not round or adjust it."
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setResultForm({ open: false, code: '', value: '', method: '', remarks: '' })}
            >
              Close
            </Button>
            <Button
              size="sm"
              loading={busy}
              disabled={!resultForm.code || resultForm.value === ''}
              onClick={() =>
                act(async () => {
                  await laboratoryService.recordResult(test.id, {
                    parameter_code: resultForm.code,
                    value: resultForm.value,
                    ...(resultForm.method ? { method: resultForm.method } : {}),
                    ...(resultForm.remarks ? { remarks: resultForm.remarks } : {}),
                  });
                  setResultForm({ open: false, code: '', value: '', method: '', remarks: '' });
                })
              }
            >
              Save the measurement
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          <Select
            label="Parameter"
            name="parameter_code"
            value={resultForm.code}
            onChange={(event) => setResultForm((form) => ({ ...form, code: event.target.value }))}
            placeholder="Choose a parameter"
            options={available.map((parameter) => ({
              value: parameter.code,
              label: `${parameter.name} (${parameter.unit_label})${parameter.is_required ? ' — required' : ''}`,
            }))}
          />
          <Input
            label={`Measured value${selectedParameter ? ` (${selectedParameter.unit_label})` : ''}`}
            name="value"
            type="number"
            step="0.0001"
            value={resultForm.value}
            onChange={(event) => setResultForm((form) => ({ ...form, value: event.target.value }))}
          />
          <Input
            label="Method"
            name="method"
            value={resultForm.method}
            onChange={(event) => setResultForm((form) => ({ ...form, method: event.target.value }))}
            placeholder="For example: refractometer"
          />
          <Input
            label="Remarks"
            name="remarks"
            value={resultForm.remarks}
            onChange={(event) => setResultForm((form) => ({ ...form, remarks: event.target.value }))}
          />
          {selectedParameter && !selectedParameter.is_configured ? (
            <Alert variant="info">
              No reference range is configured for {selectedParameter.name}, so this measurement will be
              stored as recorded and marked <strong>Not evaluated</strong>. The platform does not invent
              a limit.
            </Alert>
          ) : null}
        </div>
      </Modal>

      {/* Correct a measurement */}
      <Modal
        open={Boolean(editingResult)}
        onClose={() => setEditingResult(null)}
        title="Correct a measured value"
        description="The value being replaced is written to the audit log with the correction."
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setEditingResult(null)}>
              Close
            </Button>
            <Button
              size="sm"
              loading={busy}
              onClick={() =>
                act(async () => {
                  await laboratoryService.updateResult(test.id, editingResult.id, {
                    value: editingResult.value,
                    correction_reason: 'Corrected while the test was open',
                  });
                  setEditingResult(null);
                })
              }
            >
              Save the correction
            </Button>
          </div>
        }
      >
        {editingResult ? (
          <div className="space-y-3">
            <p className="text-sm text-ink-soft">
              {editingResult.parameter_name} — recorded {measurementText(editingResult)}
            </p>
            <Input
              label="Corrected value"
              name="corrected_value"
              type="number"
              step="0.0001"
              value={editingResult.value}
              onChange={(event) => setEditingResult({ ...editingResult, value: event.target.value })}
            />
          </div>
        ) : null}
      </Modal>

      {/* Complete the test — the verdict is computed, not chosen */}
      <Modal
        open={completeOpen}
        onClose={() => setCompleteOpen(false)}
        title="Complete the test"
        description="The platform decides PASS, FAIL or INCONCLUSIVE from the recorded values and the configured ranges."
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setCompleteOpen(false)}>
              Close
            </Button>
            <Button
              size="sm"
              loading={busy}
              onClick={() =>
                act(async () => {
                  await laboratoryService.completeTest(test.id, { remarks: completeRemarks.trim() || undefined });
                  setCompleteOpen(false);
                  setCompleteRemarks('');
                })
              }
            >
              Complete and decide
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          <ul className="space-y-1 text-sm text-ink-soft">
            <li>
              Required parameters recorded: {test.required_parameters.length - test.missing_required_parameters.length} of{' '}
              {test.required_parameters.length || 0}
              {test.missing_required_parameters.length
                ? ` (missing: ${test.missing_required_parameters.join(', ')})`
                : ''}
            </li>
            <li>
              Measurements evaluated against a configured range:{' '}
              {test.results.filter((result) => result.evaluated).length} of {test.results.length}
            </li>
            <li>
              A required parameter that fails ⇒ the test fails. A required parameter that cannot be
              judged ⇒ the test is inconclusive, and the batch stays in testing.
            </li>
          </ul>
          <Input
            label="Remarks"
            name="complete_remarks"
            value={completeRemarks}
            onChange={(event) => setCompleteRemarks(event.target.value)}
            placeholder="Anything the record should carry"
          />
        </div>
      </Modal>

      {/* Administrator override */}
      <Modal
        open={overrideOpen}
        onClose={() => setOverrideOpen(false)}
        title="Override the outcome"
        description="An override is an administrative act: it is restricted to administrators, requires a reason, and is audited with the computed result it replaced."
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setOverrideOpen(false)}>
              Close
            </Button>
            <Button
              size="sm"
              variant="danger"
              loading={busy}
              disabled={override.reason.trim().length < 10}
              onClick={() =>
                act(async () => {
                  await laboratoryService.overrideTest(test.id, {
                    overallResult: override.result,
                    reason: override.reason.trim(),
                  });
                  setOverrideOpen(false);
                  setOverride({ result: 'PASS', reason: '' });
                })
              }
            >
              Record the override
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          <p className="text-sm text-ink-soft">
            The platform computed <strong>{test.overall_result_label || test.overall_result}</strong> from
            the recorded values. The override is stored alongside it, never in place of it.
          </p>
          <Select
            label="Outcome"
            name="override_result"
            value={override.result}
            onChange={(event) => setOverride({ ...override, result: event.target.value })}
            options={[
              { value: 'PASS', label: 'Pass' },
              { value: 'FAIL', label: 'Fail' },
              { value: 'INCONCLUSIVE', label: 'Inconclusive' },
            ]}
          />
          <Input
            label="Reason"
            name="override_reason"
            value={override.reason}
            onChange={(event) => setOverride({ ...override, reason: event.target.value })}
            hint="At least 10 characters — this is what a reviewer will read."
            required
          />
        </div>
      </Modal>
    </div>
  );
}

export default LabTestPanel;
