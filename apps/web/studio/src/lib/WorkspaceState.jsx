import React, { createContext, useContext, useState } from "react";

const Context = createContext(null);

// Mounted above Routes: internal links preserve drafts, workspace selection and edits.
// App keys this tree by authenticated owner (or local session generation).
export function WorkspaceState({ children }) {
  const [drafts, setDrafts] = useState({});
  const [spaces, setSpaces] = useState([]);
  const [selected, setSelected] = useState(null);
  const [settings, setSettings] = useState({});
  const [chatDraft, setChatDraft] = useState({
    selected: null,
    title: "",
    messages: {},
    recipients: {},
    permissions: {},
    project: "",
  });
  const [projectDraft, setProjectDraft] = useState({
    selected: "",
    workspaceId: "",
    forms: {},
    recipients: {},
    roles: {},
  });
  return (
    <Context.Provider
      value={{
        drafts,
        setDrafts,
        spaces,
        setSpaces,
        selected,
        setSelected,
        settings,
        setSettings,
        chatDraft,
        setChatDraft,
        projectDraft,
        setProjectDraft,
      }}
    >
      {children}
    </Context.Provider>
  );
}

export const useWorkspaceState = () => useContext(Context);
