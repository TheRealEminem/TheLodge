import { CheckSquareIcon, PlusIcon } from "@core/components/icons";
import { useLive } from "@core/live";
import type { ModuleWeb } from "@core/registry";
import { navigate } from "@core/router";
import { NavCount } from "@core/Sidebar";
import { tasksApi } from "./api";
import { MountainIcon } from "./icons";
import MyTasks from "./MyTasks";
import ProjectPage, { ProjectBoard } from "./ProjectPage";
import Projects from "./Projects";
import TaskPage from "./TaskPage";
import TasksHome from "./TasksHome";

/** The sidebar's count: your tasks that are late or due today (nothing when there are none). */
function DueCount() {
  const { data } = useLive(() => tasksApi.count("mine"));
  return <NavCount n={data ? data.late + data.due_today : undefined} />;
}

const tasks: ModuleWeb = {
  id: "tasks",
  name: "Projects",
  nav: [
    { label: "My tasks", icon: <CheckSquareIcon size={16} />, path: "tasks", badge: DueCount },
    { label: "Projects", icon: <MountainIcon size={16} />, path: "tasks/projects" },
  ],
  routes: [
    { path: "tasks", view: MyTasks },
    { path: "tasks/t/:id", view: TaskPage },
    { path: "tasks/projects", view: Projects },
    { path: "tasks/projects/:id", view: ProjectPage },
    { path: "tasks/projects/:id/board", view: ProjectBoard, wide: true },
  ],
  primary: { label: "New task", icon: <PlusIcon size={16} />, run: () => navigate("tasks?new=1") },
  home: TasksHome,
};

export default tasks;
