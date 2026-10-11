// The People module's web half: what it adds to the sidebar, its pages and its block on Home.
import { LibraryIcon, NetworkIcon, OrgIcon, UsersIcon } from "@core/components/icons";
import type { ModuleWeb } from "@core/registry";
import HomeBlock from "./Home";
import Library from "./Library";
import Network from "./Network";
import Organizations from "./Organizations";
import People from "./People";
import Profile from "./Profile";

const crm: ModuleWeb = {
  id: "crm",
  name: "People",
  nav: [
    { label: "People", icon: <UsersIcon size={16} />, path: "crm/people" },
    { label: "Organizations", icon: <OrgIcon size={16} />, path: "crm/organizations" },
    { label: "Network", icon: <NetworkIcon size={16} />, path: "crm/network" },
    { label: "Meetings and documents", icon: <LibraryIcon size={16} />, path: "crm/meetings" },
  ],
  routes: [
    { path: "crm/people", view: People },
    { path: "crm/organizations", view: Organizations },
    { path: "crm/network", view: Network, wide: true },
    { path: "crm/meetings", view: (p) => <Library {...p} params={{ kind: "meeting" }} /> },
    { path: "crm/documents", view: (p) => <Library {...p} params={{ kind: "document" }} /> },
    { path: "crm/topics", view: (p) => <Library {...p} params={{ kind: "topic" }} /> },
    { path: "crm/e/:id", view: Profile },
  ],
  home: HomeBlock,
  homeWide: true,
};

export default crm;
