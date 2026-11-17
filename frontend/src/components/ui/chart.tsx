"use client";
/* shadcn/ui chart wrapper for Recharts (loosely typed to stay compatible with recharts 3). */
import * as React from "react";
import * as RechartsPrimitive from "recharts";
import { cn } from "@/lib/utils";

export type ChartConfig = Record<string, { label?: React.ReactNode; color?: string }>;

const ChartContext = React.createContext<{ config: ChartConfig } | null>(null);
export function useChart() {
  const ctx = React.useContext(ChartContext);
  if (!ctx) throw new Error("useChart must be used within a ChartContainer");
  return ctx;
}

export const ChartContainer = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div"> & { config: ChartConfig; children: React.ReactElement }
>(({ id, className, children, config, ...props }, ref) => {
  const uid = React.useId();
  const chartId = `chart-${id || uid.replace(/:/g, "")}`;
  const vars = Object.entries(config).reduce<Record<string, string>>((acc, [k, v]) => {
    if (v.color) acc[`--color-${k}`] = v.color;
    return acc;
  }, {});
  return (
    <ChartContext.Provider value={{ config }}>
      <div
        data-chart={chartId}
        ref={ref}
        style={vars as React.CSSProperties}
        className={cn(
          "flex aspect-video justify-center text-xs [&_.recharts-cartesian-axis-tick_text]:fill-muted-foreground [&_.recharts-cartesian-axis-tick_text]:font-mono [&_.recharts-cartesian-grid_line]:stroke-border [&_.recharts-curve.recharts-tooltip-cursor]:stroke-border [&_.recharts-surface]:outline-none",
          className,
        )}
        {...props}
      >
        <RechartsPrimitive.ResponsiveContainer>{children}</RechartsPrimitive.ResponsiveContainer>
      </div>
    </ChartContext.Provider>
  );
});
ChartContainer.displayName = "ChartContainer";

export const ChartTooltip = RechartsPrimitive.Tooltip;

/* eslint-disable @typescript-eslint/no-explicit-any */
export function ChartTooltipContent({
  active, payload, label, className, labelFormatter, valueFormatter, statusFor, hideLabel,
}: {
  active?: boolean;
  payload?: any[];
  label?: any;
  className?: string;
  labelFormatter?: (label: any, payload: any[]) => React.ReactNode;
  /** Format a series value for display; must render null as UNAVAILABLE (never 0). */
  valueFormatter?: (value: any, name: string, item: any) => React.ReactNode;
  /** Optional explicit status line (point status / reason) shown under the values. */
  statusFor?: (payload: any[]) => React.ReactNode;
  hideLabel?: boolean;
}) {
  const { config } = useChart();
  if (!active || !payload || !payload.length) return null;
  return (
    <div className={cn("grid min-w-[10rem] gap-1.5 border border-border bg-background px-2.5 py-1.5 text-xs shadow-none", className)}>
      {!hideLabel && <div className="font-mono tabular-nums tracking-tight font-medium">{labelFormatter ? labelFormatter(label, payload) : label}</div>}
      <div className="grid gap-1">
        {payload.map((item, i) => {
          const key = String(item.dataKey ?? item.name ?? i);
          const cfg = config[key];
          const raw = item.value;
          return (
            <div key={key + i} className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <span className="h-2 w-2 shrink-0" style={{ background: item.color || item.payload?.fill || `var(--color-${key})` }} />
                {cfg?.label ?? item.name ?? key}
              </span>
              <span className="font-mono tabular-nums tracking-tight font-medium">
                {valueFormatter ? valueFormatter(raw, key, item) : raw === null || raw === undefined ? "UNAVAILABLE" : String(raw)}
              </span>
            </div>
          );
        })}
      </div>
      {statusFor && <div className="border-t border-border pt-1 text-xs text-muted-foreground">{statusFor(payload)}</div>}
    </div>
  );
}

export const ChartLegend = RechartsPrimitive.Legend;

export function ChartLegendContent({ payload, className }: { payload?: any[]; className?: string }) {
  const { config } = useChart();
  if (!payload?.length) return null;
  return (
    <div className={cn("flex flex-wrap items-center justify-center gap-4 pt-2", className)}>
      {payload.map((item) => {
        const key = String(item.dataKey ?? item.value);
        return (
          <div key={key} className="flex items-center gap-1.5 text-muted-foreground">
            <span className="h-2 w-2" style={{ background: item.color }} />
            {config[key]?.label ?? item.value}
          </div>
        );
      })}
    </div>
  );
}
