import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center rounded-none border px-1.5 py-0.5 text-xs font-medium uppercase tracking-wide font-mono", {
  variants: {
    variant: {
      default: "border-border text-foreground",
      emerald: "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
      amber: "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400",
      orange: "border-orange-500/40 bg-orange-500/10 text-orange-600 dark:text-orange-400",
      rose: "border-rose-500/40 bg-rose-500/10 text-rose-600 dark:text-rose-400",
      zinc: "border-zinc-500/40 bg-zinc-500/10 text-zinc-600 dark:text-zinc-400",
    },
  },
  defaultVariants: { variant: "default" },
});

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
