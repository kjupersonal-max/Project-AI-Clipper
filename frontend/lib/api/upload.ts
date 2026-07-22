import { API_BASE_URL } from "@/lib/config";

export type UploadResult = {
  project_id: string;
  filename: string;
  stored_path: string;
  size_bytes: number;
  status: string;
};

export type UploadError = {
  message: string;
  status?: number;
};

type UploadVideoOptions = {
  file: File;
  onProgress: (percent: number) => void;
};

type UploadVideoHandle = {
  promise: Promise<UploadResult>;
  abort: () => void;
};

function parseErrorMessage(xhr: XMLHttpRequest): string {
  try {
    const payload = JSON.parse(xhr.responseText) as { detail?: string | Array<{ msg: string }> };
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
    if (Array.isArray(payload.detail) && payload.detail[0]?.msg) {
      return payload.detail[0].msg;
    }
  } catch {
    // Fall through to generic message.
  }

  if (xhr.status === 413) {
    return "File exceeds the maximum upload size.";
  }

  if (xhr.status >= 500) {
    return "Server error while uploading. Please try again.";
  }

  return xhr.statusText || "Upload failed. Please try again.";
}

export function uploadVideo({
  file,
  onProgress,
}: UploadVideoOptions): UploadVideoHandle {
  const xhr = new XMLHttpRequest();
  const formData = new FormData();
  formData.append("file", file, file.name);

  const promise = new Promise<UploadResult>((resolve, reject) => {
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as UploadResult);
        } catch {
          reject({ message: "Invalid response from server." } satisfies UploadError);
        }
        return;
      }

      reject({
        message: parseErrorMessage(xhr),
        status: xhr.status,
      } satisfies UploadError);
    });

    xhr.addEventListener("error", () => {
      reject({
        message: "Network error. Check that the backend is running.",
      } satisfies UploadError);
    });

    xhr.addEventListener("abort", () => {
      reject({ message: "Upload cancelled." } satisfies UploadError);
    });

    xhr.open("POST", `${API_BASE_URL}/api/uploads`);
    xhr.send(formData);
  });

  return {
    promise,
    abort: () => xhr.abort(),
  };
}
