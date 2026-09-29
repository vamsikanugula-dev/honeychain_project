/**
 * KVIC cluster service — basic cluster management and membership.
 *
 * Cluster-level analytics are a later phase; nothing here computes or displays
 * production figures.
 */

import { ENDPOINTS } from '@/constants/api';
import { http } from '@/services/apiClient';

export async function listClusters({ page = 1, pageSize = 20, search, district, state, isActive } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.clusters.list, {
    params: {
      page,
      page_size: pageSize,
      ...(search ? { search } : {}),
      ...(district ? { district } : {}),
      ...(state ? { state } : {}),
      ...(isActive === undefined || isActive === null ? {} : { is_active: isActive }),
    },
  });
  return { clusters: data, meta };
}

export async function getCluster(clusterId) {
  const { data } = await http.get(ENDPOINTS.clusters.detail(clusterId));
  return data;
}

/** Create a cluster. Omit `cluster_code` and the backend generates one. */
export async function createCluster(payload) {
  const { data } = await http.post(ENDPOINTS.clusters.list, payload);
  return data;
}

export async function updateCluster(clusterId, changes) {
  const { data } = await http.put(ENDPOINTS.clusters.detail(clusterId), changes);
  return data;
}

export async function setClusterStatus(clusterId, isActive, reason) {
  const { data } = await http.patch(ENDPOINTS.clusters.status(clusterId), {
    is_active: isActive,
    ...(reason ? { reason } : {}),
  });
  return data;
}

export async function listClusterMembers(clusterId, { page = 1, pageSize = 20 } = {}) {
  const { data, meta } = await http.get(ENDPOINTS.clusters.members(clusterId), {
    params: { page, page_size: pageSize },
  });
  return { members: data, meta };
}

export async function addClusterMember(clusterId, beekeeperId) {
  const { data } = await http.post(ENDPOINTS.clusters.member(clusterId, beekeeperId));
  return data;
}

export async function removeClusterMember(clusterId, beekeeperId) {
  const { data } = await http.delete(ENDPOINTS.clusters.member(clusterId, beekeeperId));
  return data;
}
