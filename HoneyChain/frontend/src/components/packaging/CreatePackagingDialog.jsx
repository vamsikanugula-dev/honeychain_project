import { useEffect, useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { SelectWithOther } from '@/components/ui/SelectWithOther';
import { PACKAGING_TYPES } from '@/constants/packaging';
import { formatNumber } from '@/utils/format';

/**
 * Opening a packaging run against an approved batch.
 *
 * The dialog's only job is to collect what the operator knows and let the server
 * check it. It shows the approved quantity, what is already packed and what is
 * therefore left — read from the batch — and refuses, before sending anything, a
 * quantity that is not a positive number, a count that is not a whole number, or
 * a figure that plainly exceeds the remainder. The server checks all of it again,
 * because a client-side check is a courtesy and never the rule.
 *
 * Nothing here can set a status or a code: a run is `PENDING` because the server
 * says so, and it is numbered `HC-PACK-…` by the server too.
 */
export function CreatePackagingDialog({
  open,
  onClose,
  batch = null,
  units = [],
  onSubmit,
  submitting = false,
  error = null,
}) {
  const [form, setForm] = useState({
    packaging_unit_id: '',
    packaging_type: 'JAR',
    packaging_type_other: '',
    packaged_quantity: '',
    package_size: '',
    number_of_packages: '',
    notes: '',
  });
  const [fieldErrors, setFieldErrors] = useState({});

  const remaining = batch ? Number(batch.remaining_quantity || 0) : 0;

  useEffect(() => {
    if (!open) return;
    setForm({
      packaging_unit_id: units[0]?.id || '',
      packaging_type: 'JAR',
      packaging_type_other: '',
      // The remainder is the natural first suggestion, and it is still only a
      // suggestion: the operator can pack less, never more.
      packaged_quantity: remaining > 0 ? String(remaining) : '',
      package_size: '',
      number_of_packages: '',
      notes: '',
    });
    setFieldErrors({});
  }, [open, units, remaining]);

  const setField = (field) => (event) => {
    const { value } = event.target;
    setForm((current) => ({ ...current, [field]: value }));
  };

  function validate() {
    const errors = {};
    const quantity = Number(form.packaged_quantity);
    const size = Number(form.package_size);
    const count = Number(form.number_of_packages);

    if (!form.packaging_unit_id) {
      errors.packaging_unit_id = 'Choose the packaging unit that is doing the work.';
    }
    if (form.packaging_type === 'OTHER' && !form.packaging_type_other.trim()) {
      errors.packaging_type_other = 'Say what the container is: "Other" on its own records nothing.';
    }
    if (!form.packaged_quantity || Number.isNaN(quantity) || quantity <= 0) {
      errors.packaged_quantity = 'Enter how much honey is being packed, as a positive number.';
    } else if (quantity > remaining) {
      errors.packaged_quantity = `Only ${formatNumber(remaining)} is left to pack on this batch.`;
    }
    if (!form.package_size || Number.isNaN(size) || size <= 0) {
      errors.package_size = 'Enter the size of one package, as a positive number.';
    }
    if (
      !form.number_of_packages ||
      Number.isNaN(count) ||
      !Number.isInteger(count) ||
      count <= 0
    ) {
      errors.number_of_packages = 'Enter how many packages are being filled, as a whole number.';
    } else if (!Number.isNaN(size) && size > 0) {
      const total = size * count;
      if (Math.abs(total - quantity) > 0.0001) {
        errors.number_of_packages = `${count} × ${formatNumber(size)} is ${formatNumber(total)}, not ${formatNumber(quantity)}.`;
      }
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  }

  function handleSubmit(event) {
    event?.preventDefault();
    if (!validate()) return;
    onSubmit?.({
      batch_id: batch.id,
      packaging_unit_id: form.packaging_unit_id,
      packaging_type: form.packaging_type,
      ...(form.packaging_type === 'OTHER'
        ? { packaging_type_other: form.packaging_type_other.trim() }
        : {}),
      packaged_quantity: form.packaged_quantity,
      package_size: form.package_size,
      number_of_packages: Number(form.number_of_packages),
      ...(form.notes.trim() ? { notes: form.notes.trim() } : {}),
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Open a packaging run"
      description={
        batch
          ? `${batch.batch_code} · ${formatNumber(batch.approved_quantity)} ${batch.unit_label || ''} approved, ${formatNumber(batch.packaged_quantity)} already packed`
          : undefined
      }
      size="lg"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} loading={submitting} data-testid="submit-packaging">
            Open the run
          </Button>
        </div>
      }
    >
      <form className="space-y-4" onSubmit={handleSubmit}>
        {error ? <Alert variant="error">{error}</Alert> : null}

        <div className="rounded-lg border border-sand-300 bg-sand-50 px-4 py-3 text-sm">
          <p className="text-ink-soft">
            Approval available to pack:{' '}
            <span className="font-medium text-ink">
              {formatNumber(remaining)} {batch?.unit_label || ''}
            </span>
          </p>
          <p className="mt-1 text-xs text-ink-muted">
            This is the laboratory-approved quantity minus everything already packed on this batch.
            It is read from the batch&apos;s records and cannot be increased here.
          </p>
        </div>

        <Select
          label="Packaging unit"
          name="packaging_unit_id"
          required
          value={form.packaging_unit_id}
          onChange={setField('packaging_unit_id')}
          error={fieldErrors.packaging_unit_id}
          options={units.map((unit) => ({
            value: unit.id,
            label: `${unit.name} · ${unit.unit_code}`,
          }))}
          placeholder={units.length ? 'Choose a unit' : 'No unit registered yet'}
        />

        <SelectWithOther
          label="Packaging type"
          name="packaging_type"
          required
          value={form.packaging_type}
          onChange={setField('packaging_type')}
          options={PACKAGING_TYPES}
          otherValue={form.packaging_type_other}
          onOtherChange={(text) => setForm((current) => ({ ...current, packaging_type_other: text }))}
          otherLabel="Specify the container"
          otherPlaceholder="For example: 500 g glass jar with brass lid"
          error={fieldErrors.packaging_type_other}
          hint="What the honey goes into. Choose Other for containers outside the list."
        />

        <div className="grid gap-4 sm:grid-cols-3">
          <Input
            label={`Honey being packed (${batch?.unit_label || 'unit'})`}
            name="packaged_quantity"
            type="number"
            step="0.001"
            min="0"
            required
            value={form.packaged_quantity}
            onChange={setField('packaged_quantity')}
            error={fieldErrors.packaged_quantity}
          />
          <Input
            label={`Size of one package (${batch?.unit_label || 'unit'})`}
            name="package_size"
            type="number"
            step="0.001"
            min="0"
            required
            value={form.package_size}
            onChange={setField('package_size')}
            error={fieldErrors.package_size}
          />
          <Input
            label="Number of packages"
            name="number_of_packages"
            type="number"
            step="1"
            min="1"
            required
            value={form.number_of_packages}
            onChange={setField('number_of_packages')}
            error={fieldErrors.number_of_packages}
          />
        </div>

        <Input
          label="Notes"
          name="notes"
          value={form.notes}
          onChange={setField('notes')}
          hint="Optional. Anything the next person reading this run should know."
        />
      </form>
    </Modal>
  );
}

export default CreatePackagingDialog;
