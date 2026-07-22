import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { aiInsights, type AIInsight } from "@/lib/mock-data";
import { cn } from "@/lib/utils";
import { Lightbulb, Sparkles, TrendingUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";

const insightConfig: Record<
  AIInsight["type"],
  { icon: LucideIcon; accent: string }
> = {
  opportunity: {
    icon: Sparkles,
    accent: "text-zinc-300",
  },
  trend: {
    icon: TrendingUp,
    accent: "text-zinc-300",
  },
  recommendation: {
    icon: Lightbulb,
    accent: "text-zinc-300",
  },
};

export function AIInsights() {
  const insights = aiInsights;

  return (
    <Card>
      <CardHeader
        title="AI Insights"
        description="Recommendations based on your content performance"
      />
      <CardContent className="p-0">
        {insights.length === 0 ? (
          <EmptyState
            icon={Sparkles}
            title="No insights yet"
            description="Process a few VODs to unlock AI-powered recommendations for your clips."
          />
        ) : (
          <ul className="divide-y divide-zinc-800/60">
            {insights.map((insight) => {
              const config = insightConfig[insight.type];
              const Icon = config.icon;

              return (
                <li key={insight.id} className="flex gap-4 px-5 py-4">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900">
                    <Icon
                      className={cn("h-4 w-4", config.accent)}
                      strokeWidth={1.75}
                    />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-zinc-200">
                      {insight.title}
                    </p>
                    <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                      {insight.description}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
