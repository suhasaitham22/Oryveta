import {readFileSync,existsSync} from "node:fs";import {resolve} from "node:path";
const base=resolve(import.meta.dirname,"..");
for(const file of ["src/App.jsx","src/index.css","src/lib/identity.js","src/components/ui/button.jsx","src/components/ui/tabs.jsx","src/pages/DemoStudio.jsx","src/pages/Workspace.jsx","public/demo-stories.json","components.json"]){if(!existsSync(resolve(base,file)))throw Error("Missing "+file);}
const code=readFileSync(resolve(base,"src/lib/identity.js"),"utf8");
if(/service_role|sb_secret_/.test(code))throw Error("Privileged credentials are not permitted in browser");
if(!code.includes("oauthGitHubEnabled=false"))throw Error("OAuth permission flag changed without auth review");
const stories=JSON.parse(readFileSync(resolve(base,"public/demo-stories.json"),"utf8"));if(!Array.isArray(stories)||stories.length<3)throw Error("Every initial story needs a demo");for(const s of stories){if(!s.id||!s.title||!s.scenes||s.scenes.length<3||s.state==="complete"&&!s.evidence)throw Error("Invalid demo story: "+s.id)}
console.log("React + shadcn component structure, auth gate and demo contracts OK");
