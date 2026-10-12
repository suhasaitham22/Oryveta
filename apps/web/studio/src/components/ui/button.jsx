import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "studio-button inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-[#f5d84c] text-[#292819] hover:bg-[#ebcc35]",
        outline:
          "border border-[#c2c9b8] bg-transparent text-[#30392a] hover:bg-[#e8ecdf]",
        ghost: "text-[#62695a] hover:bg-[#e9eddf]",
        secondary: "bg-[#e5edcf] text-[#344126] hover:bg-[#d9e6ba]",
        destructive: "bg-red-700 text-white hover:bg-red-800",
      },
      size: {
        default: "h-11 px-5 py-2",
        sm: "h-9 px-3",
        lg: "h-12 px-6",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export const Button = React.forwardRef(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Component = asChild ? Slot : "button";
    return (
      <Component
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";
