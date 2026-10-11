import { CheckSquareIcon } from "@core/components/icons";
import { useLive } from "@core/live";
import type { ModuleWeb } from "@core/registry";
import { NavCount } from "@core/Sidebar";
import { tasksApi } from "./api";
import TasksView, { TasksHome } from "./TasksView";

function OpenCount() {
  const { data } = useLive(tasksApi.count);
  return <NavCount n={data?.open} />;
}

const tasks: ModuleWeb = {
  id: "tasks",
  name: "Tasks",
  nav: [{ label: "Tasks", icon: <CheckSquareIcon size={16} />, path: "tasks", badge: OpenCount }],
  routes: [{ path: "tasks", view: TasksView }],
  home: TasksHome,
};

export default tasks;
