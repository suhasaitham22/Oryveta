import path from "node:path";
import { Config } from "@remotion/cli/config";
Config.overrideBundlerConfig(config=>({...config,resolve:{...config.resolve,alias:{...config.resolve?.alias,"@":path.resolve(process.cwd(),"src")}}}));
