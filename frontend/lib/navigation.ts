import {
  BarChart3,
  Clapperboard,
  Film,
  LayoutDashboard,
  Scissors,
  Settings,
  Sparkles,
  Upload,
  Workflow,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  label: string;
  href: string;
  icon: LucideIcon;
};

export const mainNavItems: NavItem[] = [
  { label: "Dashboard", href: "/", icon: LayoutDashboard },
  { label: "Upload VOD", href: "/upload", icon: Upload },
  { label: "Projects", href: "/projects", icon: Film },
  { label: "Clip Candidates", href: "/clip-candidates", icon: Scissors },
  { label: "Editor", href: "/editor", icon: Clapperboard },
  { label: "Publishing", href: "/publishing", icon: Sparkles },
  { label: "Analytics", href: "/analytics", icon: BarChart3 },
  { label: "Automation", href: "/automation", icon: Workflow },
  { label: "Settings", href: "/settings", icon: Settings },
];
