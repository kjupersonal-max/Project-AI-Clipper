import {
  ALLOWED_VIDEO_EXTENSIONS,
  ALLOWED_VIDEO_MIME_TYPES,
  MAX_UPLOAD_SIZE_BYTES,
} from "@/lib/config";
import { formatFileSize } from "@/lib/utils";

export type VideoValidationResult =
  | { valid: true }
  | { valid: false; message: string };

function getExtension(filename: string): string {
  const dotIndex = filename.lastIndexOf(".");
  return dotIndex >= 0 ? filename.slice(dotIndex).toLowerCase() : "";
}

export function getVideoTypeLabel(file: File): string {
  const extension = getExtension(file.name);
  const labels: Record<string, string> = {
    ".mp4": "MP4",
    ".mov": "MOV",
    ".mkv": "MKV",
    ".webm": "WebM",
  };

  if (extension in labels) {
    return labels[extension];
  }

  if (file.type) {
    return file.type;
  }

  return "Unknown";
}

export function validateVideoFile(file: File): VideoValidationResult {
  const extension = getExtension(file.name);

  if (
    !ALLOWED_VIDEO_EXTENSIONS.includes(
      extension as (typeof ALLOWED_VIDEO_EXTENSIONS)[number],
    )
  ) {
    return {
      valid: false,
      message: `Unsupported file type. Allowed formats: ${ALLOWED_VIDEO_EXTENSIONS.join(", ")}`,
    };
  }

  if (
    file.type &&
    !ALLOWED_VIDEO_MIME_TYPES.includes(
      file.type as (typeof ALLOWED_VIDEO_MIME_TYPES)[number],
    )
  ) {
    return {
      valid: false,
      message: `Unsupported video type "${file.type}". Please upload MP4, MOV, MKV, or WebM.`,
    };
  }

  if (file.size === 0) {
    return {
      valid: false,
      message: "The selected file is empty. Choose a valid video file.",
    };
  }

  if (file.size > MAX_UPLOAD_SIZE_BYTES) {
    return {
      valid: false,
      message: `File is too large. Maximum size is ${formatFileSize(MAX_UPLOAD_SIZE_BYTES)}.`,
    };
  }

  return { valid: true };
}
