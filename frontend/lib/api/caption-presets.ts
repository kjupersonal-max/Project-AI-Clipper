import { API_BASE_URL } from "@/lib/config";
import type {
  CaptionPreset,
  CaptionPresetExportPayload,
  CaptionPresetImportPayload,
  CaptionPresetListResponse,
  CaptionPresetStyle,
} from "@/lib/caption-presets";

export type ApiError = {
  message: string;
  status?: number;
};

async function parseError(response: Response): Promise<ApiError> {
  try {
    const payload = (await response.json()) as { detail?: string | Array<{ msg?: string }> };
    if (typeof payload.detail === "string") {
      return { message: payload.detail, status: response.status };
    }
    if (Array.isArray(payload.detail) && payload.detail[0]?.msg) {
      return { message: payload.detail[0].msg ?? "Request failed.", status: response.status };
    }
  } catch {
    // ignore parse errors
  }
  return { message: response.statusText || "Request failed.", status: response.status };
}

export async function fetchCaptionPresets(): Promise<CaptionPresetListResponse> {
  const response = await fetch(`${API_BASE_URL}/api/caption-presets`);
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export async function createCaptionPreset(request: {
  name: string;
  style: CaptionPresetStyle;
}): Promise<CaptionPreset> {
  const response = await fetch(`${API_BASE_URL}/api/caption-presets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export async function updateCaptionPreset(
  presetId: string,
  request: {
    name?: string;
    style?: CaptionPresetStyle;
    is_default?: boolean;
  },
): Promise<CaptionPreset> {
  const response = await fetch(`${API_BASE_URL}/api/caption-presets/${presetId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export async function deleteCaptionPreset(presetId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/caption-presets/${presetId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw await parseError(response);
  }
}

export async function duplicateCaptionPreset(presetId: string): Promise<CaptionPreset> {
  const response = await fetch(`${API_BASE_URL}/api/caption-presets/${presetId}/duplicate`, {
    method: "POST",
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export async function exportCaptionPreset(presetId: string): Promise<CaptionPresetExportPayload> {
  const response = await fetch(`${API_BASE_URL}/api/caption-presets/${presetId}/export`);
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export async function importCaptionPresets(
  payload: CaptionPresetImportPayload,
): Promise<{ imported: CaptionPreset[] }> {
  const response = await fetch(`${API_BASE_URL}/api/caption-presets/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}
