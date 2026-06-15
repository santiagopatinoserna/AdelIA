import { Loader2 } from "lucide-react";

// Shown during async data fetches across dashboard routes — a calm branded
// spinner instead of a blank flash.
export default function DashboardLoading() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <Loader2 className="h-8 w-8 animate-spin text-pine-400" strokeWidth={2} aria-label="…" />
    </div>
  );
}
