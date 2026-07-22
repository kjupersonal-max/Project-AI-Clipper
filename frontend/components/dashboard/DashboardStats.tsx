import { StatCard } from "@/components/ui/StatCard";
import { dashboardStats } from "@/lib/mock-data";
import { formatCurrency, formatNumber } from "@/lib/utils";
import { Clapperboard, DollarSign, Eye, Video } from "lucide-react";

export function DashboardStats() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard
        label="Videos Processed"
        value={formatNumber(dashboardStats.videosProcessed)}
        change="+12 this month"
        icon={Video}
      />
      <StatCard
        label="Clips Generated"
        value={formatNumber(dashboardStats.clipsGenerated)}
        change="+86 this month"
        icon={Clapperboard}
      />
      <StatCard
        label="Total Views"
        value={formatNumber(dashboardStats.totalViews)}
        change="+18.4% vs last month"
        icon={Eye}
      />
      <StatCard
        label="Estimated Revenue"
        value={formatCurrency(dashboardStats.estimatedRevenue)}
        change="+$2,140 this month"
        icon={DollarSign}
      />
    </div>
  );
}
