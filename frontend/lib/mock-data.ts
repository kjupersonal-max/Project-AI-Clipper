export type ProjectStatus = "ready" | "processing" | "draft" | "published";

export type RecentProject = {
  id: string;
  title: string;
  source: string;
  clipsGenerated: number;
  status: ProjectStatus;
  updatedAt: string;
  thumbnailColor: string;
};

export type QueueItem = {
  id: string;
  title: string;
  stage: "transcribing" | "analyzing" | "generating" | "rendering";
  progress: number;
  eta: string;
};

export type AIInsight = {
  id: string;
  title: string;
  description: string;
  type: "opportunity" | "trend" | "recommendation";
};

export const dashboardStats = {
  videosProcessed: 128,
  clipsGenerated: 842,
  totalViews: 2_450_000,
  estimatedRevenue: 18_420,
};

export const recentProjects: RecentProject[] = [
  {
    id: "proj-001",
    title: "Valorant Ranked Grind — Week 12",
    source: "Twitch VOD · 4h 32m",
    clipsGenerated: 24,
    status: "ready",
    updatedAt: "2 hours ago",
    thumbnailColor: "#3F3F46",
  },
  {
    id: "proj-002",
    title: "Just Chatting — Community Q&A",
    source: "YouTube Live · 2h 08m",
    clipsGenerated: 11,
    status: "processing",
    updatedAt: "5 hours ago",
    thumbnailColor: "#27272A",
  },
  {
    id: "proj-003",
    title: "Elden Ring DLC First Playthrough",
    source: "Kick VOD · 6h 15m",
    clipsGenerated: 38,
    status: "published",
    updatedAt: "Yesterday",
    thumbnailColor: "#52525B",
  },
  {
    id: "proj-004",
    title: "IRL Stream — Tokyo Day 3",
    source: "Twitch VOD · 3h 44m",
    clipsGenerated: 0,
    status: "draft",
    updatedAt: "2 days ago",
    thumbnailColor: "#3F3F46",
  },
];

export const processingQueue: QueueItem[] = [
  {
    id: "queue-001",
    title: "Just Chatting — Community Q&A",
    stage: "analyzing",
    progress: 62,
    eta: "~18 min",
  },
  {
    id: "queue-002",
    title: "Minecraft Hardcore Ep. 47",
    stage: "transcribing",
    progress: 34,
    eta: "~42 min",
  },
  {
    id: "queue-003",
    title: "Speedrun Attempt — Any%",
    stage: "generating",
    progress: 81,
    eta: "~9 min",
  },
];

export const aiInsights: AIInsight[] = [
  {
    id: "insight-001",
    title: "High-engagement moments detected",
    description:
      "3 clips from your Valorant session scored above 92% retention potential. Review and publish while momentum is high.",
    type: "opportunity",
  },
  {
    id: "insight-002",
    title: "Short-form trend alignment",
    description:
      "Reaction-style clips under 45 seconds are outperforming longer edits by 2.3× this week across your niche.",
    type: "trend",
  },
  {
    id: "insight-003",
    title: "Publishing schedule suggestion",
    description:
      "Your audience peaks Tue–Thu between 6–9 PM EST. Queue 2 clips per day during that window for optimal reach.",
    type: "recommendation",
  },
];
