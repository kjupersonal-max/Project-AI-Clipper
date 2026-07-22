import type { CandidateExportState } from "@/lib/clip-export";
import { Button } from "@/components/ui/Button";
import { AlertCircle, CheckCircle2, Loader2, Upload } from "lucide-react";

type ClipExportButtonProps = {
  exportState?: CandidateExportState;
  isExported: boolean;
  isExporting: boolean;
  onExport: () => void;
};

export function ClipExportButton({
  exportState,
  isExported,
  isExporting,
  onExport,
}: ClipExportButtonProps) {
  const exportFailed = exportState?.status === "failed";
  const exportDisabled = isExported || isExporting;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant={isExported ? "secondary" : "primary"}
          size="sm"
          disabled={exportDisabled}
          onClick={onExport}
          icon={
            isExporting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : isExported ? (
              <CheckCircle2 className="h-3.5 w-3.5" />
            ) : (
              <Upload className="h-3.5 w-3.5" />
            )
          }
        >
          {isExporting
            ? "Exporting..."
            : isExported
              ? "Exported"
              : exportFailed
                ? "Retry Export"
                : "Export"}
        </Button>
        {exportFailed && exportState?.error ? (
          <p className="inline-flex items-center gap-1 text-xs text-red-300">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            {exportState.error}
          </p>
        ) : null}
      </div>
    </div>
  );
}
