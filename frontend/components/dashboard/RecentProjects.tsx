import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { recentProjects, type ProjectStatus } from "@/lib/mock-data";
import { ArrowRight, Film } from "lucide-react";

const statusConfig: Record<
  ProjectStatus,
  { label: string; variant: "success" | "warning" | "info" | "muted" }
> = {
  ready: { label: "Ready", variant: "success" },
  processing: { label: "Processing", variant: "warning" },
  draft: { label: "Draft", variant: "muted" },
  published: { label: "Published", variant: "info" },
};

export function RecentProjects() {
  const projects = recentProjects;

  return (
    <Card>
      <CardHeader
        title="Recent Projects"
        description="Your latest VOD processing sessions"
        action={
          <Button variant="ghost" size="sm" icon={<ArrowRight className="h-3.5 w-3.5" />}>
            View all
          </Button>
        }
      />
      <CardContent className="p-0">
        {projects.length === 0 ? (
          <EmptyState
            icon={Film}
            title="No projects yet"
            description="Upload a VOD to start generating clip candidates automatically."
          />
        ) : (
          <ul className="divide-y divide-zinc-800/60">
            {projects.map((project) => {
              const status = statusConfig[project.status];

              return (
                <li
                  key={project.id}
                  className="flex items-center gap-4 px-5 py-4 transition-colors hover:bg-zinc-900/30"
                >
                  <div
                    className="hidden h-12 w-20 shrink-0 rounded-md border border-zinc-800 sm:block"
                    style={{ backgroundColor: project.thumbnailColor }}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-zinc-200">
                      {project.title}
                    </p>
                    <p className="mt-0.5 truncate text-xs text-zinc-500">
                      {project.source}
                    </p>
                  </div>
                  <div className="hidden text-right sm:block">
                    <p className="text-sm font-medium text-zinc-300">
                      {project.clipsGenerated} clips
                    </p>
                    <p className="mt-0.5 text-xs text-zinc-600">
                      {project.updatedAt}
                    </p>
                  </div>
                  <Badge variant={status.variant}>{status.label}</Badge>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
