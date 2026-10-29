import React, { useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  Clapperboard,
  Download,
  FileText,
  HardDrive,
  Info,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { downloadJson } from "@/lib/download";
import DemoStudio from "./DemoStudio.jsx";
import LocalRun from "@/components/LocalRun.jsx";

export const emptyDraft = () => ({
  name: "",
  brief: "",
  story: {},
  projectId: null,
  jobId: null,
  blueprint: "python-api",
});

export default function Journey({
  kind,
  stories,
  draft,
  onChange,
  engine,
  selfHosted,
  workspaceId,
}) {
  const [exported, setExported] = useState(false);
  const briefTab = useRef(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get("tab") || "brief";
  function selectTab(value) {
    if (value === tab) return;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("tab", value);
      return next;
    });
  }
  const isNew = kind === "start-new";
  const title = isNew ? "Start New" : "Evolve";
  function edit(values) {
    setExported(false);
    onChange(values);
  }
  function exportBrief(event) {
    event.preventDefault();
    downloadJson(`oryveta-${kind}-brief.json`, {
      title: draft.name,
      brief: draft.brief,
      workflow: kind,
      kind: "planning-brief",
      status: "not-executed",
      demoStory: kind,
      created_at: new Date().toISOString(),
    });
    setExported(true);
  }
  if (!["brief", "local", "demo"].includes(tab))
    return (
      <div className="surface-panel">
        <h1>Unknown workflow tab.</h1>
        <p>
          This address doesn't identify a Brief, Local run or Demo Studio tab.
        </p>
        <Button asChild>
          <Link to={isNew ? "/workspace/new" : "/workspace/evolve"}>
            Return to {title}
          </Link>
        </Button>
      </div>
    );
  return (
    <div>
      <div className="page-heading journey-heading">
        <div>
          <h1>{title}</h1>
          <p>
            {isNew
              ? "Describe the app you need and export its brief. Prepare starter code with the self-hosted engine."
              : "Describe a change, inspect source with the self-hosted engine, and review the findings before editing code."}
          </p>
        </div>
        {draft.name && (
          <div className="journey-context">
            <FileText size={17} />
            <div><strong>{draft.name}</strong><span>Current brief · in this workspace</span></div>
          </div>
        )}
      </div>
      <Tabs value={tab} onValueChange={selectTab} activationMode="manual">
        <TabsList className="journey-tab-list" aria-label={`${title} workflow`}>
          <TabsTrigger ref={briefTab} value="brief">
            <FileText size={15} />
            Brief
          </TabsTrigger>
          <TabsTrigger value="local">
            <HardDrive size={15} />
            Local run
          </TabsTrigger>
          <TabsTrigger value="demo">
            <Clapperboard size={15} />
            Demo Studio
          </TabsTrigger>
        </TabsList>
        <TabsContent value="brief">
          <div className="brief-layout">
            <form className="surface-panel brief-form" onSubmit={exportBrief}>
              <div className="section-label">01 / Define the outcome</div>
              <h2>
                {isNew
                  ? "What should this help someone do?"
                  : "What needs to work better?"}
              </h2>
              <label className="field-label">
                {isNew ? "Project name" : "Repository URL or name"}
                <Input
                  required
                  minLength={2}
                  maxLength={isNew ? 90 : 180}
                  value={draft.name}
                  onChange={(event) => edit({ name: event.target.value })}
                  placeholder={
                    isNew
                      ? "e.g. Client onboarding portal"
                      : "e.g. Customer billing service"
                  }
                />
              </label>
              <label className="field-label">
                {isNew ? "Describe the product" : "What should be improved?"}
                <Textarea
                  required
                  minLength={10}
                  maxLength={2500}
                  rows={6}
                  value={draft.brief}
                  onChange={(event) => edit({ brief: event.target.value })}
                  placeholder={
                    isNew
                      ? "Who uses it? What should they be able to do? Include acceptance criteria and constraints."
                      : "Describe the current behavior, desired change, and the regressions to avoid."
                  }
                />
              </label>
              <div className="form-actions">
                <Button type="submit">
                  <Download size={15} />
                  Export brief
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => selectTab("demo")}
                >
                  Write demo script <ArrowRight size={15} />
                </Button>
              </div>
              {exported && (
                <p role="status" className="notice">
                  Planning brief exported. Execution not initiated.
                </p>
              )}
              <p className="fine-print">
                Brief and demo edits stay in this open workspace. Export a
                copy before closing or reloading the page.
              </p>
            </form>
            <aside className="journey-guide" aria-label="Workflow guidance">
              <div className="section-label">Keep the scope useful</div>
              <h3>What happens next?</h3>
              <ol>
                <li>
                  <span>01</span>
                  <div>
                    <strong>Define</strong>
                    <p>Record the customer task and what success means.</p>
                  </div>
                </li>
                <li>
                  <span>02</span>
                  <div>
                    <strong>
                      {isNew ? "Prepare locally" : "Inspect locally"}
                    </strong>
                    <p>
                      {isNew
                        ? "Create a template starter, then analyze its source."
                        : "Import a ZIP and inspect static findings. No code is executed."}
                    </p>
                  </div>
                </li>
                <li>
                  <span>03</span>
                  <div>
                    <strong>Explain</strong>
                    <p>Write a demo script to show the intended user experience.</p>
                  </div>
                </li>
              </ol>
              <Button variant="outline" onClick={() => selectTab("local")}>
                {isNew ? "Prepare locally" : "Inspect locally"} <ArrowRight size={15} />
              </Button>
              <div className="boundary-note">
                <Info size={17} />
                <p>
                  These are workflow options, not completed tasks. Hosted
                  coding, test execution and deployment are not connected.
                </p>
              </div>
            </aside>
          </div>
        </TabsContent>
        <TabsContent value="local">
          <LocalRun
            key={engine.user?.id || "signed-out"}
            engine={engine}
            kind={kind}
            draft={draft}
            onChange={onChange}
            selfHosted={selfHosted}
          />
        </TabsContent>
        <TabsContent value="demo">
          <Button
            type="button"
            variant="ghost"
            className="demo-return"
            onClick={() => {
              selectTab("brief");
              briefTab.current?.focus();
            }}
          >
            <ArrowLeft size={16} aria-hidden="true" />
            Back to brief
          </Button>
          <DemoStudio
            stories={stories}
            storyId={kind}
            draft={draft.story}
            onChange={(values) =>
              onChange({ story: { ...draft.story, ...values } })
            }
            context={{
              journey: kind,
              title: draft.name,
              brief: draft.brief,
              workspaceId,
              projectId: draft.projectId,
            }}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
