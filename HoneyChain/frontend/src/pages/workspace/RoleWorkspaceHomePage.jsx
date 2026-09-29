import { workspaceForRole, workspaceLabelForRole } from '@/constants/navigation';
import { PLANNED_MODULES } from '@/constants/plannedModules';
import { roleLabel } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';
import { Badge } from '@/components/ui/Badge';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { WorkspaceHeader } from '@/components/common/WorkspaceHeader';
import { PlannedModuleNotice } from '@/components/common/PlannedModuleNotice';
import { Button } from '@/components/ui/Button';

/**
 * The home screen of a role whose module is not built yet.
 *
 * This is the honest middle ground between two bad options. The role is real, the
 * account is real, and the platform has a place for them — but the module they
 * work in does not exist yet. So they get their own workspace, their own name, a
 * statement of what it will contain, and **no navigation into anybody else's
 * module**: nothing borrowed, nothing faked, and no "you are in the wrong
 * workspace" message, because they are in exactly the right one.
 */
export default function RoleWorkspaceHomePage() {
  const { user } = useAuth();
  const role = user?.role;
  const workspace = workspaceForRole(role);
  const planned = PLANNED_MODULES.find((module) => module.path === workspace?.home) || null;

  return (
    <div className="space-y-6">
      <WorkspaceHeader
        title={workspaceLabelForRole(role)}
        description={workspace?.description || 'Your workspace on HoneyChain.'}
        requiredRoles={[role]}
      />

      <Card>
        <CardHeader
          title="Your account is ready"
          description="Signed in and scoped correctly. The module below is what your role works in."
          action={
            <Badge variant="honey" size="sm">
              {roleLabel(role)}
            </Badge>
          }
        />
        <CardBody className="space-y-4">
          <p className="text-sm leading-relaxed text-ink-soft">
            HoneyChain runs one traceable record per honey batch from the apiary onwards. Your part of
            that journey is described below; until it ships, nothing here pretends to be a working
            screen, and you cannot reach — or see links to — the modules belonging to other roles.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button to="/profile" size="sm" variant="secondary">
              Review my profile
            </Button>
            <Button to="/how-it-works" size="sm" variant="ghost">
              How the platform fits together
            </Button>
          </div>
        </CardBody>
      </Card>

      {planned ? (
        <PlannedModuleNotice
          phase={planned.phase}
          title={`${planned.title} is not part of this release`}
          description={planned.description}
          features={planned.features}
        />
      ) : (
        <PlannedModuleNotice
          phase="A later phase"
          title="Your module is not part of this release"
          description="The screens for this role are being built in a later phase. When they arrive they will appear in this workspace's sidebar — nowhere else."
          features={[]}
        />
      )}
    </div>
  );
}
