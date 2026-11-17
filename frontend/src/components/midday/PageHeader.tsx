import type { ReactNode } from "react";

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 pb-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-xs text-muted-foreground">{description}</p>}
      </div>
      {actions}
    </div>
  );
}

/** Titled placeholder used by route skeletons until page content is built. */
export function PagePlaceholder({ title, description }: { title: string; description?: string }) {
  return (
    <div>
      <PageHeader title={title} description={description} />
      <div className="border border-dashed border-border p-8 text-xs text-muted-foreground">Content for &quot;{title}&quot; is not built yet.</div>
    </div>
  );
}
