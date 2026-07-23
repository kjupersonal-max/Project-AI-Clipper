export function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function formatNumber(value: number): string {
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`;
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(1)}K`;
  }
  return value.toLocaleString();
}

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";

  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1,
  );
  const value = bytes / 1024 ** index;

  return `${value >= 10 || index === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[index]}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const remaining = total % 60;
  return minutes > 0 ? `${minutes}m ${remaining}s` : `${remaining}s`;
}

export type UniqueListItem = {
  key: string;
  text: string;
};

export function uniqueStringListItems(
  items: readonly string[] | null | undefined,
  keyPrefix = "item",
): UniqueListItem[] {
  if (!items?.length) {
    return [];
  }

  const seen = new Set<string>();
  const result: UniqueListItem[] = [];

  items.forEach((text, index) => {
    if (seen.has(text)) {
      return;
    }
    seen.add(text);
    result.push({
      key: `${keyPrefix}-${index}`,
      text,
    });
  });

  return result;
}
