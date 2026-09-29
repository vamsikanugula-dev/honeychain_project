import { Spinner } from '@/components/ui/Spinner';

/** Centred loading indicator with an optional message, for page-level waits. */
export function LoadingState({ message = 'Loading…', className = '' }) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-3 px-6 py-12 text-center ${className}`}
      role="status"
      aria-live="polite"
    >
      <Spinner size="lg" className="text-honey-500" />
      <p className="text-sm text-ink-muted">{message}</p>
    </div>
  );
}

/** Skeleton block used while structured content loads, to avoid layout shift. */
export function SkeletonBlock({ className = '' }) {
  return <div className={`animate-pulse rounded-lg bg-sand-200 ${className}`} aria-hidden="true" />;
}

export default LoadingState;
