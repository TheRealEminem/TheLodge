import { LeafIcon } from "@core/components/icons";
import type { ModuleWeb } from "@core/registry";
import { ItemView, ListView } from "./views";

const module: ModuleWeb = {
  id: "__id__",
  name: "__Name__",
  nav: [{ label: "__Name__", icon: <LeafIcon size={16} />, path: "__id__" }],
  routes: [
    { path: "__id__", view: ListView },
    { path: "__id__/:id", view: ItemView },
  ],
};

export default module;
