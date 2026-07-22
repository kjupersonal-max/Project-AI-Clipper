import { ProjectDetails } from "@/components/projects/ProjectDetails";

type ProjectPageProps = {
  params: Promise<{ projectId: string }>;
};

export default async function ProjectPage({ params }: ProjectPageProps) {
  const { projectId } = await params;

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <ProjectDetails projectId={projectId} />
    </div>
  );
}
