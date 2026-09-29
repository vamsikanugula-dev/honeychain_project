/** Real HoneyChain backend endpoints for Fabric ledger reads and QR resolution. */

import { ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';

export async function listTransactions({ search, txType, status } = {}) {
  const { data } = await http.get(ENDPOINTS.blockchain.transactions, {
    params: {
      ...(search ? { search } : {}),
      ...(txType ? { tx_type: txType } : {}),
      ...(status ? { status } : {}),
    },
  });
  return data;
}

export async function getBlockchainHealth() {
  const { data } = await http.get(ENDPOINTS.blockchain.health);
  return data;
}

export async function retrySynchronization(eventId = null) {
  const { data } = await http.post(ENDPOINTS.blockchain.retry, null, {
    params: eventId ? { event_id: eventId } : {},
  });
  return data;
}

export async function getBatchTraceability(batchId) {
  const { data } = await http.get(ENDPOINTS.batches.traceability(batchId));
  return data;
}

export async function generatePackageQr(packageId) {
  const { data } = await http.post(ENDPOINTS.packaging.packageQr(packageId));
  return data;
}

/** Public endpoint: an opaque QR token is sufficient; no login is sent. */
export async function getPublicTraceability(token) {
  const { data } = await http.get(ENDPOINTS.blockchain.publicTraceability(token), { skipAuth: true });
  return data;
}
