import { VideoUploader } from "@/components/upload/VideoUploader";

export default function UploadPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-8 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-50 sm:text-3xl">
          Upload VOD
        </h1>
        <p className="max-w-2xl text-sm leading-relaxed text-zinc-400">
          Upload a long-form recording to create a new project. Once uploaded,
          the file is stored securely and ready for future AI processing
          workflows.
        </p>
      </div>

      <VideoUploader />
    </div>
  );
}
