// The notes module's web half: what it adds to the sidebar, its pages, its Home card and its settings.
import { NoteIcon, PlusIcon } from "@core/components/icons";
import type { ModuleWeb } from "@core/registry";
import { navigate } from "@core/router";
import { notesApi } from "./api";
import { NotesHome, NotesSettings } from "./extras";
import NoteView from "./NoteView";
import NotesList from "./NotesList";

const notes: ModuleWeb = {
  id: "notes",
  name: "Notes",
  nav: [{ label: "Notes", icon: <NoteIcon size={16} />, path: "notes" }],
  routes: [
    { path: "notes", view: NotesList },
    { path: "notes/:id", view: NoteView },
  ],
  primary: {
    label: "New note",
    icon: <PlusIcon size={18} />,
    run: async () => navigate(`notes/${(await notesApi.create()).id}`),
  },
  home: NotesHome,
  settings: NotesSettings,
};

export default notes;
