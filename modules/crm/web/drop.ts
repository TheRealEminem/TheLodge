// Getting files out of a drop or a file picker, folders included (with their paths, which give the AI context).

export interface Picked {
  file: File;
  path: string;
}

const hidden = (path: string) => path.split("/").some((part) => part.startsWith("."));   // .DS_Store, .git…

async function walk(entry: FileSystemEntry, prefix: string): Promise<Picked[]> {
  const path = prefix + entry.name;
  if (entry.isFile) {
    const file = await new Promise<File>((ok, fail) => (entry as FileSystemFileEntry).file(ok, fail));
    return [{ file, path }];
  }
  if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    const out: Picked[] = [];
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((ok, fail) => reader.readEntries(ok, fail));
      if (!batch.length) break;
      for (const child of batch) out.push(...(await walk(child, `${path}/`)));
    }
    return out;
  }
  return [];
}

/** What was dropped. Folders are read in full (WebKit's directory entries), keeping their relative paths. */
export async function fromDrop(data: DataTransfer): Promise<Picked[]> {
  // The entries must be taken now, while the drop event is still alive.
  const entries = [...data.items].map((i) => i.webkitGetAsEntry?.()).filter((e): e is FileSystemEntry => Boolean(e));
  const found = entries.length ? (await Promise.all(entries.map((e) => walk(e, "")))).flat() : [...data.files].map((file) => ({ file, path: file.name }));
  return found.filter((p) => !hidden(p.path));
}

/** What a file or folder picker returned. */
export function fromInput(list: FileList | null): Picked[] {
  if (!list) return [];
  return [...list]
    .map((file) => ({ file, path: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name }))
    .filter((p) => !hidden(p.path));
}
