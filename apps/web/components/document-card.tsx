import { Link } from "@/lib/navigation";
import type { DocumentDTO } from "@/lib/api-client";
import { StatusBadge } from "./status-badge";

export function DocumentCard({ doc, locale }: { doc: DocumentDTO; locale: string }) {
  const fileName = doc.file_name;
  return (
    <Link
      href={`/dashboard/documents/${doc.id}`}
      className="block rounded-lg border border-slate-200 bg-white p-4 hover:border-slate-300"
    >
      <div className="flex items-center justify-between">
        <span className="truncate text-sm font-medium">{fileName}</span>
        <StatusBadge status={doc.status} />
      </div>
      <p className="mt-2 text-xs text-slate-500">
        {new Date(doc.created_at).toLocaleString()}
      </p>
    </Link>
  );
}
