import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
export default defineConfig(({mode}) => ({
 base: mode === "selfhost" ? "/studio/" : "/",
 plugins: [react(), tailwindcss()],
 resolve:{alias:{"@":path.resolve(process.cwd(),"src")}},
 build:{outDir: mode === "selfhost" ? "dist-local" : "dist",emptyOutDir:true,cssCodeSplit:true},
 server:{host:"127.0.0.1"}
}));
