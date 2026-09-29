import { ROLES } from '@/constants/roles';

/**
 * Modules that are declared but not built.
 *
 * This file is a *roadmap*, not a navigation source. Nothing here is routed and
 * nothing here appears in a sidebar: a module is described to the role it belongs
 * to, on that role's own workspace home, and it is deleted from this list the
 * moment a real screen replaces it. That is what keeps the honest description of
 * what is missing from turning into a link to a screen that does not exist.
 *
 * An entry is deleted the moment a real screen replaces it: processing and the
 * laboratory were built in Phase 6, and packaging, distribution and retail in
 * Phase 7, so their entries are gone and working pages stand in their place.
 */

export const PLANNED_MODULES = [
  {
    path: '/collection-center',
    roles: [ROLES.COLLECTION_CENTER],
    title: 'Collection centre workspace',
    phase: 'Supply-chain phase',
    description:
      'Receipt of honey from beekeepers in your area and handover onward, with the traceability record that connects both ends.',
    features: [
      'Receive honey against a beekeeper',
      'Weight and quality checks at intake',
      'Handover to a processor',
      'Intake history',
    ],
  },
  {
    path: '/consumer',
    roles: [ROLES.CONSUMER],
    title: 'Consumer verification',
    phase: 'Verification phase',
    description:
      'Scanning a jar to read the journey of the honey inside it. The QR identity and the public verification page are part of a later phase; nothing is generated here yet.',
    features: [
      'Scan a jar and see its batch',
      'See the beekeeper and district of origin',
      'See the quality checks recorded for the batch',
      'Report a concern about a product',
    ],
  },
  {
    path: '/kvic/production',
    roles: [ROLES.KVIC_OFFICER],
    title: 'Production reports',
    phase: 'Analytics phase',
    description:
      'Aggregated production and quality reporting over the records the platform already holds for your clusters.',
    features: [
      'Harvest volumes by cluster and season',
      'Quality outcome trends',
      'District-level roll-ups',
      'Export-ready summaries',
    ],
  },
  {
    path: '/admin/system',
    roles: [ROLES.ADMIN],
    title: 'System settings',
    phase: 'Operations phase',
    description:
      'Platform configuration and operational status: integrations, retention and the service health page.',
    features: [
      'Integration configuration (MQTT, storage)',
      'Service health and version information',
      'Retention settings for logs',
    ],
  },
];

export const PLANNED_MODULE_BY_PATH = Object.fromEntries(
  PLANNED_MODULES.map((module) => [module.path, module]),
);
