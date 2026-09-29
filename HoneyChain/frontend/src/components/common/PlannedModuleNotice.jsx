import { CalendarClock, Info } from 'lucide-react';

import { Card, CardBody } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';

/**
 * Honest placeholder used by every role workspace in Phase 1.
 *
 * It states what the workspace will contain and in which phase it arrives,
 * instead of rendering fake charts or empty widgets that look like broken
 * features.
 */
export function PlannedModuleNotice({ phase, title, description, features = [] }) {
  return (
    <Card className="border-dashed border-sand-400 bg-sand-100/50">
      <CardBody>
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white text-honey-700 ring-1 ring-sand-300">
            <CalendarClock size={18} aria-hidden="true" />
          </span>
          <h2 className="text-base font-semibold text-ink">{title}</h2>
          <Badge variant="pending" size="sm">
            {phase}
          </Badge>
        </div>
        <p className="mt-3 max-w-3xl text-sm leading-relaxed text-ink-soft">{description}</p>
        {features.length ? (
          <ul className="mt-4 grid gap-2 sm:grid-cols-2">
            {features.map((feature) => (
              <li key={feature} className="flex items-start gap-2 text-sm text-ink-soft">
                <Info size={15} className="mt-0.5 flex-none text-honey-600" aria-hidden="true" />
                {feature}
              </li>
            ))}
          </ul>
        ) : null}
      </CardBody>
    </Card>
  );
}

export default PlannedModuleNotice;
