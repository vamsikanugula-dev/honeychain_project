import { useEffect, useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { normaliseError } from '@/utils/errors';
import { clusterSchema } from '@/utils/validation';
import { useToast } from '@/hooks/useToast';
import * as clusterService from '@/services/clusterService';

const EMPTY = {
  clusterName: '',
  district: '',
  state: '',
  description: '',
  coordinatorName: '',
  coordinatorPhone: '',
};

function toPayload(values) {
  return {
    cluster_name: values.clusterName,
    district: values.district,
    state: values.state,
    description: values.description || null,
    coordinator_name: values.coordinatorName || null,
    coordinator_phone: values.coordinatorPhone || null,
  };
}

/**
 * Create or edit a KVIC cluster.
 *
 * The cluster code is not an input: the backend generates `KVIC-<DIST>-001` so
 * codes stay unique and sequential. It is shown read-only when editing, because
 * it is immutable and may already be printed on records.
 */
export function ClusterFormModal({ open, cluster = null, onClose, onSaved }) {
  const toast = useToast();
  const [formError, setFormError] = useState(null);
  const isEdit = Boolean(cluster);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm({ resolver: zodResolver(clusterSchema), defaultValues: EMPTY });

  useEffect(() => {
    if (!open) return;
    reset(
      cluster
        ? {
            clusterName: cluster.cluster_name || '',
            district: cluster.district || '',
            state: cluster.state || '',
            description: cluster.description || '',
            coordinatorName: cluster.coordinator_name || '',
            coordinatorPhone: cluster.coordinator_phone || '',
          }
        : EMPTY,
    );
    setFormError(null);
  }, [open, cluster, reset]);

  const onSubmit = async (values) => {
    setFormError(null);
    try {
      const payload = toPayload(values);
      const saved = isEdit
        ? await clusterService.updateCluster(cluster.id, payload)
        : await clusterService.createCluster(payload);
      toast.success(isEdit ? 'Cluster updated' : `Cluster ${saved.cluster_code} created`);
      onSaved?.(saved);
      onClose?.();
    } catch (caught) {
      setFormError(normaliseError(caught));
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'Edit cluster' : 'Create a KVIC cluster'}
      description={
        isEdit
          ? `${cluster.cluster_code} · the code cannot be changed`
          : 'The cluster code is generated automatically from the district.'
      }
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button type="submit" form="cluster-form" loading={isSubmitting}>
            {isEdit ? 'Save changes' : 'Create cluster'}
          </Button>
        </>
      }
    >
      <form id="cluster-form" onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        {formError ? <Alert variant="danger">{formError.message}</Alert> : null}

        <Input
          label="Cluster name"
          name="clusterName"
          required
          error={errors.clusterName?.message}
          {...register('clusterName')}
        />

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="District"
            name="district"
            required
            error={errors.district?.message}
            {...register('district')}
          />
          <Input
            label="State"
            name="state"
            required
            error={errors.state?.message}
            {...register('state')}
          />
          <Input
            label="Coordinator name"
            name="coordinatorName"
            error={errors.coordinatorName?.message}
            {...register('coordinatorName')}
          />
          <Input
            label="Coordinator phone"
            name="coordinatorPhone"
            error={errors.coordinatorPhone?.message}
            {...register('coordinatorPhone')}
          />
        </div>

        <Input
          label="Description"
          name="description"
          error={errors.description?.message}
          hint="Optional. Anything that helps identify the cluster later."
          {...register('description')}
        />
      </form>
    </Modal>
  );
}

export default ClusterFormModal;
