export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const MAX_UPLOAD_SIZE_BYTES = Number(
  process.env.NEXT_PUBLIC_MAX_UPLOAD_SIZE_BYTES ?? 5 * 1024 * 1024 * 1024,
);

export const ALLOWED_VIDEO_EXTENSIONS = [".mp4", ".mov", ".mkv", ".webm"] as const;

export const ALLOWED_VIDEO_MIME_TYPES = [
  "video/mp4",
  "video/quicktime",
  "video/x-matroska",
  "video/webm",
  "video/mkv",
] as const;
