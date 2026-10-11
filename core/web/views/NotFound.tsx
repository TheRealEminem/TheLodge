import { SignpostIcon } from "../components/icons";
import { ContourBadge } from "../components/illustrations";

export default function NotFound() {
  return (
    <div className="inset-surface mt-10 px-4 py-12 text-center">
      <ContourBadge>
        <SignpostIcon size={20} />
      </ContourBadge>
      <p className="mt-3 font-medium">Off the trail</p>
      <p className="mx-auto mt-1 max-w-sm text-label leading-relaxed text-ink-soft">
        There's nothing here. It may have been deleted, or its module is turned off.
      </p>
      <a href="#/" className="btn btn-sm btn-soft mt-5">
        Back to Home
      </a>
    </div>
  );
}
