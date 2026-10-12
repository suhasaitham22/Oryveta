import * as React from "react";
import { cn } from "@/lib/utils";

export const Textarea = React.forwardRef(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "flex min-h-32 w-full resize-y rounded-md border border-[#cbd2c0] bg-[#fcfdf9] p-4 text-sm leading-relaxed text-[#303a26] placeholder:text-[#7b856e] focus-visible:border-[#7b9855] disabled:opacity-50",
      className,
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";
