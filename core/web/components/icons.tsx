// One icon family for the whole app: Lucide, 1.8 stroke, currentColor.
// Sizes: 16 for everyday UI, 18 for important controls, 20 for primary actions.
import {
  ArrowUp,
  AudioLines,
  Backpack,
  CalendarDays,
  Check,
  ChevronDown,
  Circle,
  Clock,
  Cloud,
  Columns2,
  Compass,
  Copy,
  Flag,
  Folder,
  KeyRound,
  Laptop,
  Leaf,
  Lock,
  ListChecks,
  Menu,
  MessageSquareText,
  Mic,
  Monitor,
  Moon,
  Pause,
  PenLine,
  Play,
  Plus,
  Power,
  RotateCw,
  Search,
  Share,
  Signpost,
  SlidersHorizontal,
  Sparkles,
  Square,
  Sun,
  Text,
  Trash2,
  TreePine,
  TriangleAlert,
  Users,
  X,
  Download,
  ArrowLeft,
  House,
  NotebookPen,
  LogOut,
  Building2,
  FileText,
  Hash,
  Waypoints,
  Inbox,
  ChevronRight,
  Library,
  Mail,
  Phone,
  MapPin,
  ExternalLink,
  GitMerge,
  UserRound,
} from "lucide-react";
import type { LucideIcon, LucideProps } from "lucide-react";

export type IconProps = Omit<LucideProps, "ref"> & { size?: number };

export function icon(Base: LucideIcon, fixed: Partial<LucideProps> = {}) {
  const Icon = ({ size = 16, strokeWidth = 1.8, ...rest }: IconProps) => (
    <Base size={size} strokeWidth={strokeWidth} aria-hidden="true" focusable={false} {...fixed} {...rest} />
  );
  return Icon;
}

export const MicIcon = icon(Mic);
export const StopIcon = icon(Square, { fill: "currentColor" });
export const RecordIcon = icon(Circle, { fill: "currentColor", stroke: "none" });
export const SlidersIcon = icon(SlidersHorizontal);
export const TrashIcon = icon(Trash2);
export const ExportIcon = icon(Share);
export const CopyIcon = icon(Copy);
export const CheckIcon = icon(Check);
export const PencilIcon = icon(PenLine);
export const SparkleIcon = icon(Sparkles);
export const AlertIcon = icon(TriangleAlert);
export const DownloadIcon = icon(Download);
export const RefreshIcon = icon(RotateCw);
export const FolderIcon = icon(Folder);
export const CloseIcon = icon(X);
export const MonitorIcon = icon(Monitor);
export const SunIcon = icon(Sun);
export const LeafIcon = icon(Leaf);
export const CompassIcon = icon(Compass);
export const SignpostIcon = icon(Signpost);
export const PineIcon = icon(TreePine);
export const ClockIcon = icon(Clock);
export const CalendarIcon = icon(CalendarDays);
export const PlusIcon = icon(Plus);
export const LinesIcon = icon(Text);
export const ColumnsIcon = icon(Columns2);
export const BackpackIcon = icon(Backpack);
export const FlagIcon = icon(Flag);
export const WaveIcon = icon(AudioLines);
export const UsersIcon = icon(Users);
export const ChevronDownIcon = icon(ChevronDown);
export const PlayIcon = icon(Play, { fill: "currentColor" });
export const PauseIcon = icon(Pause, { fill: "currentColor" });
export const SearchIcon = icon(Search);
export const ChatIcon = icon(MessageSquareText);
export const CheckSquareIcon = icon(ListChecks);
export const MoonIcon = icon(Moon);
export const KeyIcon = icon(KeyRound);
export const PowerIcon = icon(Power);
export const CloudIcon = icon(Cloud);
export const LaptopIcon = icon(Laptop);
export const LockIcon = icon(Lock);
export const MenuIcon = icon(Menu);
export const ArrowUpIcon = icon(ArrowUp);
export const BackIcon = icon(ArrowLeft);
export const HomeIcon = icon(House);
export const NoteIcon = icon(NotebookPen);
export const LogOutIcon = icon(LogOut);
export const OrgIcon = icon(Building2);
export const DocIcon = icon(FileText);
export const TopicIcon = icon(Hash);
export const NetworkIcon = icon(Waypoints);
export const InboxIcon = icon(Inbox);
export const ChevronRightIcon = icon(ChevronRight);
export const LibraryIcon = icon(Library);
export const MailIcon = icon(Mail);
export const PhoneIcon = icon(Phone);
export const MapPinIcon = icon(MapPin);
export const ExternalIcon = icon(ExternalLink);
export const MergeIcon = icon(GitMerge);
export const PersonIcon = icon(UserRound);
