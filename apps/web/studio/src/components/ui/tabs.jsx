import * as React from "react";import * as TabsPrimitive from "@radix-ui/react-tabs";import {cn} from "@/lib/utils";
export const Tabs=TabsPrimitive.Root;
export const TabsList=React.forwardRef(({className,...props},ref)=><TabsPrimitive.List ref={ref} className={cn("inline-flex items-center rounded-xl bg-slate-100/80 p-1 text-slate-500",className)} {...props}/>);TabsList.displayName="TabsList";
export const TabsTrigger=React.forwardRef(({className,...props},ref)=><TabsPrimitive.Trigger ref={ref} className={cn("rounded-lg px-4 py-2 text-sm font-medium transition-colors data-[state=active]:bg-white data-[state=active]:text-indigo-700 data-[state=active]:shadow-sm",className)} {...props}/>);TabsTrigger.displayName="TabsTrigger";
export const TabsContent=React.forwardRef(({className,...props},ref)=><TabsPrimitive.Content ref={ref} className={cn("outline-none",className)} {...props}/>);TabsContent.displayName="TabsContent";
