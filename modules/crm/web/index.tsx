// The People module's web half: what it adds to the sidebar, its pages and its block on Home.
import { Suspense, lazy } from "react";
import { InboxIcon, NetworkIcon, UsersIcon } from "@core/components/icons";
import { Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import { GroupGlyph } from "./groups";
import type { ModuleWeb } from "@core/registry";
import { NavCount } from "@core/Sidebar";
import { crmApi } from "./api";
import AiSettings from "./AiSettings";
import Groups from "./GroupsPage";
import HomeBlock from "./Home";
import Library from "./Library";
import Network from "./Network";
import Organizations from "./Organizations";
import People from "./People";
import Profile from "./Profile";

// The inbox screens are only needed when you open them.
const Inbox = lazy(() => import("./Inbox"));
const InboxItem = lazy(() => import("./InboxItem"));
const later = (view: JSX.Element) => <Suspense fallback={<Skeleton className="h-64 w-full rounded-xl" />}>{view}</Suspense>;

/** What needs you: items waiting for review, and ones that failed. */
function InboxCount() {
  const { data } = useLive(crmApi.inboxSummary);
  return <NavCount n={(data?.counts.review ?? 0) + (data?.counts.failed ?? 0)} />;
}

const crm: ModuleWeb = {
  id: "crm",
  name: "People",
  nav: [
    { label: "People", icon: <UsersIcon size={16} />, path: "crm/people" },
    { label: "Network", icon: <NetworkIcon size={16} />, path: "crm/network" },
    { label: "Groups", icon: <GroupGlyph kind="organization" size={16} />, path: "crm/groups" },
    { label: "Inbox", icon: <InboxIcon size={16} />, path: "crm/inbox", badge: InboxCount },
  ],
  routes: [
    { path: "crm/people", view: People },
    { path: "crm/groups", view: Groups },
    { path: "crm/inbox", view: () => later(<Inbox />) },
    { path: "crm/inbox/:id", view: (p) => later(<InboxItem {...p} />) },
    { path: "crm/organizations", view: Organizations },
    { path: "crm/network", view: Network, wide: true },
    { path: "crm/meetings", view: (p) => <Library {...p} params={{ kind: "meeting" }} /> },
    { path: "crm/documents", view: (p) => <Library {...p} params={{ kind: "document" }} /> },
    { path: "crm/topics", view: (p) => <Library {...p} params={{ kind: "topic" }} /> },
    { path: "crm/e/:id", view: Profile },
  ],
  home: HomeBlock,
  homeWide: true,
  settings: AiSettings,
};

export default crm;
