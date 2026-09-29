import { useEffect, useMemo, useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { formatNumber } from '@/utils/format';

/**
 * Raising a shipment against a released package.
 *
 * The dialog asks which package is going, how much of it, where to and to whom.
 * The package list it offers is exactly the packages the server will accept — the
 * ones the packaging unit released and that still have honey left — because
 * offering a package that would be refused is how a caller ends up guessing at
 * the rules. Nothing can be overdrawn: the remaining quantity is shown as the
 * ceiling, and a larger figure is refused before it is sent and again by the
 * server.
 *
 * The destination may be a shop counter or a market, so it is free text; the
 * retailer is a named account, because only a retailer account may confirm a
 * receipt.
 */
export function CreateShipmentDialog({
  open,
  onClose,
  packages = [],
  packagesLoading = false,
  onSubmit,
  submitting = false,
  error = null,
}) {
  const [form, setForm] = useState({
    package_id: '',
    quantity: '',
    destination: '',
    destination_district: '',
    carrier: '',
    tracking_reference: '',
    expected_delivery_date: '',
    notes: '',
  });
  const [fieldErrors, setFieldErrors] = useState({});

  const selected = useMemo(
    () => packages.find((row) => row.id === form.package_id) || null,
    [packages, form.package_id],
  );
  const remaining = selected ? Number(selected.remaining_quantity ?? selected.quantity ?? 0) : 0;

  useEffect(() => {
    if (!open) return;
    const first = packages[0] || null;
    setForm({
      package_id: first?.id || '',
      quantity: first ? String(first.remaining_quantity ?? first.quantity ?? '') : '',
      destination: '',
      destination_district: '',
      carrier: '',
      tracking_reference: '',
      expected_delivery_date: '',
      notes: '',
    });
    setFieldErrors({});
  }, [open, packages]);

  const setField = (field) => (event) => {
    const { value } = event.target;
    setForm((current) => ({ ...current, [field]: value }));
  };

  function validate() {
    const errors = {};
    const quantity = Number(form.quantity);

    if (!form.package_id) {
      errors.package_id = 'Choose the package that is travelling.';
    }
    if (!form.quantity || Number.isNaN(quantity) || quantity <= 0) {
      errors.quantity = 'Enter how much of the package is going, as a positive number.';
    } else if (quantity > remaining) {
      errors.quantity = `This package has ${formatNumber(remaining)} left to ship.`;
    }
    if (!form.destination || form.destination.trim().length < 2) {
      errors.destination = 'Name the destination — a market, a shop or a town.';
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  }

  function handleSubmit(event) {
    event?.preventDefault();
    if (!validate()) return;
    onSubmit?.({
      package_id: form.package_id,
      quantity: form.quantity,
      destination: form.destination.trim(),
      ...(form.destination_district.trim() ? { destination_district: form.destination_district.trim() } : {}),
      ...(form.carrier.trim() ? { carrier: form.carrier.trim() } : {}),
      ...(form.tracking_reference.trim()
        ? { tracking_reference: form.tracking_reference.trim() }
        : {}),
      ...(form.expected_delivery_date ? { expected_delivery_date: form.expected_delivery_date } : {}),
      ...(form.notes.trim() ? { notes: form.notes.trim() } : {}),
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Create a shipment"
      description="One released package, one destination. The honey is counted against the package."
      size="lg"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} loading={submitting} data-testid="submit-shipment">
            Create the shipment
          </Button>
        </div>
      }
    >
      <form className="space-y-4" onSubmit={handleSubmit}>
        {error ? <Alert variant="error">{error}</Alert> : null}
        {!packagesLoading && !packages.length ? (
          <Alert variant="info">
            No package is ready for distribution. The packaging unit releases packages when the
            packing work is complete.
          </Alert>
        ) : null}

        <Select
          label="Package"
          name="package_id"
          required
          value={form.package_id}
          onChange={(event) => {
            const value = event.target.value;
            const next = packages.find((row) => row.id === value) || null;
            setForm((current) => ({
              ...current,
              package_id: value,
              quantity: next ? String(next.remaining_quantity ?? next.quantity ?? '') : '',
            }));
          }}
          error={fieldErrors.package_id}
          options={packages.map((row) => ({
            value: row.id,
            label: `${row.package_code} · ${row.batch_code} · ${formatNumber(row.remaining_quantity ?? row.quantity)} ${row.unit_label || ''} available`,
          }))}
          placeholder={packagesLoading ? 'Loading packages…' : 'Choose a package'}
        />

        {selected ? (
          <div className="rounded-lg border border-sand-300 bg-sand-50 px-4 py-3 text-sm">
            <p className="text-ink-soft">
              {selected.package_code}: {formatNumber(selected.quantity)} {selected.unit_label || ''} packed,{' '}
              <span className="font-medium text-ink">
                {formatNumber(remaining)} {selected.unit_label || ''} left to ship
              </span>
            </p>
            <p className="mt-1 text-xs text-ink-muted">
              Read from the package&apos;s own shipments. Cancelled ones hold nothing.
            </p>
          </div>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label={`Quantity being shipped (${selected?.unit_label || 'unit'})`}
            name="quantity"
            type="number"
            step="0.001"
            min="0"
            required
            value={form.quantity}
            onChange={setField('quantity')}
            error={fieldErrors.quantity}
          />
          <Input
            label="Destination"
            name="destination"
            required
            value={form.destination}
            onChange={setField('destination')}
            error={fieldErrors.destination}
            placeholder="Guntur market"
          />
          <Input
            label="Destination district"
            name="destination_district"
            value={form.destination_district}
            onChange={setField('destination_district')}
            placeholder="Optional"
          />
          <Input
            label="Carrier"
            name="carrier"
            value={form.carrier}
            onChange={setField('carrier')}
            placeholder="Optional"
          />
          <Input
            label="Tracking reference"
            name="tracking_reference"
            value={form.tracking_reference}
            onChange={setField('tracking_reference')}
            placeholder="Optional"
          />
          <Input
            label="Expected delivery"
            name="expected_delivery_date"
            type="date"
            value={form.expected_delivery_date}
            onChange={setField('expected_delivery_date')}
          />
        </div>

        <Input
          label="Notes"
          name="notes"
          value={form.notes}
          onChange={setField('notes')}
          hint="Optional. Anything the receiver should know before it arrives."
        />
      </form>
    </Modal>
  );
}

export default CreateShipmentDialog;
