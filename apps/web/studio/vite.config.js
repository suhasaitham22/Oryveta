import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import { readFileSync } from "node:fs";
import { DEFAULT_SUPABASE_URL, DEFAULT_SUPABASE_PUBLISHABLE_KEY } from "./src/lib/publicConfig.js";

function checkPublicConfiguration(env, mode) {
 const key = env.VITE_SUPABASE_PUBLISHABLE_KEY || DEFAULT_SUPABASE_PUBLISHABLE_KEY;
 let anonymousJwt = false;
 if (key.split(".").length === 3) {
  try {
   anonymousJwt = JSON.parse(Buffer.from(key.split(".")[1], "base64url").toString()).role === "anon";
  } catch { /* An invalid JWT is not a public API key. */ }
 }
 if (!key.startsWith("sb_publishable_") && !anonymousJwt)
  throw new Error("VITE_SUPABASE_PUBLISHABLE_KEY must be a publishable or anon key, never a secret or user token.");
 if (process.env.VERCEL === "1" && mode !== "selfhost") {
  const origin = new URL(env.VITE_SUPABASE_URL || DEFAULT_SUPABASE_URL).origin;
  const config = JSON.parse(readFileSync(new URL("../vercel.json", import.meta.url), "utf8"));
  const policy = config.headers.flatMap((rule) => rule.headers)
   .find((header) => header.key.toLowerCase() === "content-security-policy")?.value || "";
  const allowed = policy.split(";").map((part) => part.trim())
   .find((part) => part.startsWith("connect-src "))?.split(/\s+/).slice(1) || [];
  if (!allowed.includes(origin))
   throw new Error("The configured Supabase origin is not allowed by apps/web/vercel.json. Update its connect-src policy in the same reviewed deployment.");
 }
}
export default defineConfig(({mode}) => {
 checkPublicConfiguration(loadEnv(mode, process.cwd(), "VITE_"), mode);
 return {
 base: mode === "selfhost" ? "/studio/" : "/",
 plugins: [react(), tailwindcss()],
 resolve:{alias:{"@":path.resolve(process.cwd(),"src")}},
 build:{outDir: mode === "selfhost" ? "dist-local" : "dist",emptyOutDir:true,cssCodeSplit:true},
 server:{host:"127.0.0.1"}
 };
});
