import { AIInsights } from "@/components/dashboard/AIInsights";
import { DashboardHeader } from "@/components/dashboard/DashboardHeader";
import { DashboardStats } from "@/components/dashboard/DashboardStats";
import { ProcessingQueue } from "@/components/dashboard/ProcessingQueue";
import { RecentProjects } from "@/components/dashboard/RecentProjects";

export default function DashboardPage() {
  return (
    <div className="mx-auto max-w-7xl space-y-8 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <DashboardHeader />
      <DashboardStats />
      <div className="grid gap-6 xl:grid-cols-5">
        <div className="xl:col-span-3">
          <RecentProjects />
        </div>
        <div className="space-y-6 xl:col-span-2">
          <ProcessingQueue />
          <AIInsights />
        </div>
      </div>
    </div>
  );
}
