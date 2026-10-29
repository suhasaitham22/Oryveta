import * as React from "react";
import { cn } from "@/lib/utils";

export const Textarea = React.forwardRef(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "flex min-h-32 w-full resize-y rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 text-base md:text-sm leading-relaxed text-[var(--ink)] placeholder:text-[var(--muted)] focus-visible:border-[var(--accent)] disabled:opacity-50",
      className,
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";
