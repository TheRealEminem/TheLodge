// Sediment Analysis' web half: its place in the sidebar, its two pages and its Settings section.
import { LinesIcon } from "@core/components/icons";
import type { ModuleWeb } from "@core/registry";
import SedimentSettings from "./Settings";
import { SedimentHome, SedimentPerson } from "./views";

const sediment: ModuleWeb = {
  id: "sediment",
  name: "Sediment",
  nav: [{ label: "Sediment", icon: <LinesIcon size={16} />, path: "sediment" }],
  routes: [
    { path: "sediment", view: SedimentHome },
    { path: "sediment/:ref", view: SedimentPerson },
  ],
  settings: SedimentSettings,
};

export default sediment;
