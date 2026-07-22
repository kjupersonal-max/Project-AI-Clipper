"use client";

import { uploadVideo, type UploadResult } from "@/lib/api/upload";
import { MAX_UPLOAD_SIZE_BYTES } from "@/lib/config";
import {
  getVideoTypeLabel,
  validateVideoFile,
} from "@/lib/validation/video";
import { cn, formatFileSize } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  FileVideo,
  Upload,
  X,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

type UploadPhase = "idle" | "selected" | "uploading" | "success" | "error";

export function VideoUploader() {
  const [phase, setPhase] = useState<UploadPhase>("idle");
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);
  const uploadAbortRef = useRef<(() => void) | null>(null);

  const resetPreview = useCallback(() => {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }
    setPreviewUrl(null);
  }, [previewUrl]);

  const clearSelection = useCallback(() => {
    uploadAbortRef.current?.();
    uploadAbortRef.current = null;
    resetPreview();
    setFile(null);
    setError(null);
    setProgress(0);
    setResult(null);
    setPhase("idle");
    if (inputRef.current) {
      inputRef.current.value = "";
    }
  }, [resetPreview]);

  const selectFile = useCallback(
    (nextFile: File) => {
      uploadAbortRef.current?.();
      uploadAbortRef.current = null;

      const validation = validateVideoFile(nextFile);
      if (!validation.valid) {
        resetPreview();
        setFile(null);
        setResult(null);
        setProgress(0);
        setError(validation.message);
        setPhase("error");
        return;
      }

      resetPreview();
      setError(null);
      setResult(null);
      setProgress(0);
      setFile(nextFile);
      setPreviewUrl(URL.createObjectURL(nextFile));
      setPhase("selected");
    },
    [resetPreview],
  );

  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
      uploadAbortRef.current?.();
    };
  }, [previewUrl]);

  const handleFiles = (files: FileList | null) => {
    const nextFile = files?.[0];
    if (nextFile) {
      selectFile(nextFile);
    }
  };

  const handleUpload = async () => {
    if (!file) return;

    setPhase("uploading");
    setProgress(0);
    setError(null);

    const { promise, abort } = uploadVideo({
      file,
      onProgress: setProgress,
    });

    uploadAbortRef.current = abort;

    try {
      const response = await promise;
      uploadAbortRef.current = null;
      setResult(response);
      setPhase("success");
    } catch (uploadError) {
      uploadAbortRef.current = null;
      const message =
        uploadError &&
        typeof uploadError === "object" &&
        "message" in uploadError
          ? String(uploadError.message)
          : "Upload failed. Please try again.";

      if (message === "Upload cancelled.") {
        setProgress(0);
        setPhase("selected");
        return;
      }

      setError(message);
      setPhase("error");
    }
  };

  const handleCancelUpload = () => {
    uploadAbortRef.current?.();
    uploadAbortRef.current = null;
    setProgress(0);
    setPhase("selected");
  };

  return (
    <div className="space-y-6">
      {phase !== "success" ? (
        <Card
          className={cn(
            "overflow-hidden transition-colors",
            isDragging && "border-zinc-600 bg-zinc-900",
          )}
          onDragEnter={(event) => {
            event.preventDefault();
            setIsDragging(true);
          }}
          onDragOver={(event) => {
            event.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={(event) => {
            event.preventDefault();
            if (event.currentTarget.contains(event.relatedTarget as Node)) {
              return;
            }
            setIsDragging(false);
          }}
          onDrop={(event) => {
            event.preventDefault();
            setIsDragging(false);
            handleFiles(event.dataTransfer.files);
          }}
        >
          <CardContent className="p-0">
            <div
              className={cn(
                "flex flex-col items-center justify-center px-6 py-12 text-center sm:py-16",
                file ? "border-b border-zinc-800/60" : "",
              )}
            >
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900">
                <Upload className="h-5 w-5 text-zinc-400" strokeWidth={1.75} />
              </div>
              <h2 className="text-base font-medium text-zinc-100">
                Drag and drop your VOD here
              </h2>
              <p className="mt-2 max-w-md text-sm leading-relaxed text-zinc-500">
                MP4, MOV, MKV, or WebM up to{" "}
                {formatFileSize(MAX_UPLOAD_SIZE_BYTES)}. Your file stays local
                until you start the upload.
              </p>
              <input
                ref={inputRef}
                type="file"
                accept=".mp4,.mov,.mkv,.webm,video/mp4,video/quicktime,video/x-matroska,video/webm"
                className="hidden"
                onChange={(event) => handleFiles(event.target.files)}
              />
              <Button
                variant="secondary"
                className="mt-6"
                onClick={() => inputRef.current?.click()}
                disabled={phase === "uploading"}
              >
                Browse files
              </Button>
            </div>

            {file ? (
              <div className="grid gap-6 p-5 lg:grid-cols-2">
                <div className="space-y-4">
                  <div className="flex items-start gap-3 rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900">
                      <FileVideo className="h-4 w-4 text-zinc-400" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-zinc-200">
                        {file.name}
                      </p>
                      <dl className="mt-2 space-y-1 text-xs text-zinc-500">
                        <div className="flex justify-between gap-4">
                          <dt>Size</dt>
                          <dd className="text-zinc-400">
                            {formatFileSize(file.size)}
                          </dd>
                        </div>
                        <div className="flex justify-between gap-4">
                          <dt>Type</dt>
                          <dd className="text-zinc-400">
                            {getVideoTypeLabel(file)}
                          </dd>
                        </div>
                      </dl>
                    </div>
                  </div>

                  {phase === "uploading" ? (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-zinc-500">Uploading</span>
                        <span className="font-medium tabular-nums text-zinc-300">
                          {progress}%
                        </span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
                        <div
                          className="h-full rounded-full bg-zinc-200 transition-all duration-200"
                          style={{ width: `${progress}%` }}
                        />
                      </div>
                    </div>
                  ) : null}

                  {error ? (
                    <div className="flex items-start gap-3 rounded-lg border border-red-900/60 bg-red-950/20 px-4 py-3">
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
                      <p className="text-sm text-red-300">{error}</p>
                    </div>
                  ) : null}

                  <div className="flex flex-wrap gap-2">
                    {phase === "uploading" ? (
                      <Button variant="secondary" onClick={handleCancelUpload}>
                        Cancel upload
                      </Button>
                    ) : (
                      <>
                        <Button
                          onClick={handleUpload}
                          icon={<Upload className="h-4 w-4" />}
                        >
                          Upload VOD
                        </Button>
                        <Button variant="ghost" onClick={clearSelection}>
                          Remove
                        </Button>
                      </>
                    )}
                  </div>
                </div>

                <div className="overflow-hidden rounded-lg border border-zinc-800 bg-black">
                  {previewUrl ? (
                    <video
                      src={previewUrl}
                      controls
                      className="aspect-video w-full bg-black object-contain"
                      preload="metadata"
                    />
                  ) : null}
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {phase === "success" && result ? (
        <Card>
          <CardContent className="space-y-6 p-6">
            <div className="flex items-start gap-4">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-emerald-900/60 bg-emerald-950/40">
                <CheckCircle2 className="h-5 w-5 text-emerald-400" />
              </div>
              <div>
                <h2 className="text-lg font-medium text-zinc-100">
                  Upload complete
                </h2>
                <p className="mt-1 text-sm text-zinc-500">
                  Your VOD was saved and assigned a project ID for downstream
                  processing.
                </p>
              </div>
            </div>

            <dl className="grid gap-4 rounded-lg border border-zinc-800 bg-zinc-950/60 p-4 sm:grid-cols-2">
              <div>
                <dt className="text-xs uppercase tracking-wider text-zinc-500">
                  Project ID
                </dt>
                <dd className="mt-1 break-all font-mono text-sm text-zinc-200">
                  {result.project_id}
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wider text-zinc-500">
                  Filename
                </dt>
                <dd className="mt-1 break-all text-sm text-zinc-200">
                  {result.filename}
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wider text-zinc-500">
                  File size
                </dt>
                <dd className="mt-1 text-sm text-zinc-200">
                  {formatFileSize(result.size_bytes)}
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wider text-zinc-500">
                  Status
                </dt>
                <dd className="mt-1 text-sm capitalize text-emerald-400">
                  {result.status}
                </dd>
              </div>
            </dl>

            <div className="flex flex-wrap gap-2">
              <Link href={`/projects/${result.project_id}`}>
                <Button icon={<ArrowRight className="h-4 w-4" />}>
                  Continue to Processing
                </Button>
              </Link>
              <Button variant="secondary" onClick={clearSelection}>
                Upload another VOD
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {phase === "error" && !file ? (
        <Card>
          <CardContent className="flex items-start gap-3 p-5">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
            <div className="flex-1">
              <p className="text-sm text-red-300">{error}</p>
              <Button
                variant="ghost"
                size="sm"
                className="mt-3"
                onClick={() => {
                  setError(null);
                  setPhase("idle");
                }}
              >
                Try again
              </Button>
            </div>
            <button
              type="button"
              onClick={() => {
                setError(null);
                setPhase("idle");
              }}
              className="rounded-md p-1 text-zinc-500 hover:text-zinc-300"
              aria-label="Dismiss error"
            >
              <X className="h-4 w-4" />
            </button>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
