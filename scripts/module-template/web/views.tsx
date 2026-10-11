import { useState } from "react";
import { LinkedList } from "@core/components/blocks";
import { BackIcon, LeafIcon, PlusIcon, TrashIcon } from "@core/components/icons";
import { ContourBadge } from "@core/components/illustrations";
import { PageHeader, Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import type { RouteProps } from "@core/registry";
import { navigate } from "@core/router";
import { useShell } from "@core/shell";
import { __id__Api } from "./api";

export function ListView() {
  const { toast } = useShell();
  const { data: items } = useLive(__id__Api.list);
  const [title, setTitle] = useState("");
  const add = async () => {
    try {
      await __id__Api.create(title.trim());
      setTitle("");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  return (
    <>
      <PageHeader title="__Name__" />
      <form
        className="mb-6 flex animate-enter gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim()) void add();
        }}
      >
        <input className="field h-10 flex-1" placeholder="Add something" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Title" />
        <button className="btn btn-md btn-primary" disabled={!title.trim()}>
          <PlusIcon size={18} />
          Add
        </button>
      </form>
      {!items && <Skeleton className="h-24 w-full rounded-xl" />}
      {items?.length === 0 && (
        <div className="inset-surface animate-enter px-4 py-12 text-center">
          <ContourBadge>
            <LeafIcon size={20} />
          </ContourBadge>
          <p className="mt-3 font-medium">Nothing here yet</p>
          <p className="mx-auto mt-1 max-w-sm text-label leading-relaxed text-ink-soft">What you add will appear here.</p>
        </div>
      )}
      {!!items?.length && (
        <div className="panel animate-enter divide-y divide-line px-2">
          {items.map((i) => (
            <a key={i.id} href={`#/__id__/${i.id}`} className="block rounded-md px-3 py-3.5 text-label font-medium transition-colors hover:bg-forest/[.04]">
              {i.title}
            </a>
          ))}
        </div>
      )}
    </>
  );
}

export function ItemView({ params }: RouteProps) {
  const { confirm } = useShell();
  const { data: item, error } = useLive(() => __id__Api.get(params.id), [params.id]);
  if (error) return <p className="text-label text-ink-soft">{error}</p>;
  if (!item) return <Skeleton className="h-9 w-2/3" />;
  const remove = async () => {
    if (await confirm({ title: "Delete this?", body: "It can't be brought back.", confirmLabel: "Delete", tone: "danger" })) {
      await __id__Api.remove(item.id);
      navigate("__id__");
    }
  };
  return (
    <article className="animate-enter">
      <div className="mb-3 flex items-center justify-between">
        <a href="#/__id__" className="btn btn-sm btn-ghost -ml-3">
          <BackIcon size={16} />
          __Name__
        </a>
        <button className="icon-btn hover:!bg-trail-soft hover:!text-trail-deep" aria-label="Delete" data-tip="Delete" onClick={() => void remove()}>
          <TrashIcon size={18} />
        </button>
      </div>
      <h1 className="page-title">{item.title}</h1>
      <LinkedList of={`__id__:${item.id}`} />
    </article>
  );
}
