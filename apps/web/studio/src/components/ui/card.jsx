import * as React from "react";import {cn} from "@/lib/utils";
export const Card=React.forwardRef(({className,...props},ref)=><div ref={ref} className={cn("rounded-[22px] border border-white/75 bg-white/70 backdrop-blur-xl shadow-[0_14px_44px_rgba(37,53,103,.07)]",className)} {...props}/>);Card.displayName="Card";
export const CardHeader=({className,...props})=><div className={cn("flex flex-col space-y-1.5 p-6",className)} {...props}/>;
export const CardTitle=({className,...props})=><h3 className={cn("font-semibold tracking-tight",className)} {...props}/>;
export const CardDescription=({className,...props})=><p className={cn("text-sm text-slate-500 leading-relaxed",className)} {...props}/>;
export const CardContent=({className,...props})=><div className={cn("p-6 pt-0",className)} {...props}/>;
export const CardFooter=({className,...props})=><div className={cn("flex items-center p-6 pt-0",className)} {...props}/>;
