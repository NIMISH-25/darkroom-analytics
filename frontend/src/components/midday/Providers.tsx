"use client";
import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { EvidenceSheetProvider } from "./EvidenceSheet";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } }));
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <EvidenceSheetProvider>{children}</EvidenceSheetProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
