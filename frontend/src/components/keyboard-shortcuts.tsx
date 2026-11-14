"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

// Keys that work on every screen (frontend redesign): / goes to Search and puts the cursor in its
// box, ? lists every shortcut. A screen's own keys (J and K on Search...) live on that screen and
// are listed here so there is one place to read them all.

const OPEN_EVENT = "omnisight:shortcuts";

// The sidebar's "Keyboard shortcuts" button opens the same list as the ? key.
export function openShortcuts() {
  window.dispatchEvent(new Event(OPEN_EVENT));
}

// True while the person is typing, so a letter key types instead of acting.
export function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

// The Search page's box (moment-search.tsx).
export const SEARCH_INPUT_ID = "moment-search-q";

const GROUPS: { title: string; keys: { keys: string[]; does: string }[] }[] = [
  {
    title: "Anywhere",
    keys: [
      { keys: ["/"], does: "Search footage" },
      { keys: ["?"], does: "Show this list" },
    ],
  },
  {
    title: "Search",
    keys: [
      { keys: ["J"], does: "Next result" },
      { keys: ["K"], does: "Previous result" },
      { keys: ["Enter"], does: "Open the result" },
      { keys: ["Esc"], does: "Leave the search box" },
    ],
  },
];

export function KeyboardShortcuts() {
  const dialog = useRef<HTMLDialogElement>(null);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    const open = () => {
      if (dialog.current && !dialog.current.open) dialog.current.showModal();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || isTyping(event.target)) return;
      // Some keyboards and tools report Shift + / rather than "?".
      if (event.key === "?" || (event.key === "/" && event.shiftKey)) {
        event.preventDefault();
        open();
      } else if (event.key === "/") {
        event.preventDefault();
        const box = document.getElementById(SEARCH_INPUT_ID);
        if (pathname === "/search" && box) box.focus();
        else router.push("/search");
      }
    };
    window.addEventListener(OPEN_EVENT, open);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener(OPEN_EVENT, open);
      window.removeEventListener("keydown", onKey);
    };
  }, [pathname, router]);

  return (
    <dialog
      ref={dialog}
      aria-labelledby="shortcuts-title"
      onClick={(event) => {
        // A click on the backdrop (the dialog element itself, outside its box) closes it.
        if (event.target === dialog.current) dialog.current?.close();
      }}
      className="m-auto w-[min(92vw,460px)] rounded-lg border border-ns-line-strong bg-ns-raised p-0 text-ns-text shadow-[0_24px_64px_rgba(0,0,0,0.55)] backdrop:bg-black/60"
    >
      <div className="p-6">
        <div className="flex items-start justify-between gap-4">
          <h2 id="shortcuts-title" className="text-lg font-semibold">
            Keyboard shortcuts
          </h2>
          <button
            type="button"
            onClick={() => dialog.current?.close()}
            className="h-8 rounded-md border border-ns-line-strong px-3 text-sm text-ns-soft transition hover:text-ns-text focus-visible:ring-2 focus-visible:ring-ns-accent focus-visible:outline-none"
          >
            Close
          </button>
        </div>
        {GROUPS.map((group) => (
          <section key={group.title} className="mt-5">
            <h3 className="mb-2 text-sm text-ns-muted">{group.title}</h3>
            <dl className="space-y-1.5">
              {group.keys.map((row) => (
                <div key={row.does} className="flex items-center justify-between gap-4">
                  <dt className="text-sm text-ns-soft">{row.does}</dt>
                  <dd className="flex gap-1">
                    {row.keys.map((key) => (
                      <kbd
                        key={key}
                        className="min-w-7 rounded border border-ns-line-strong px-1.5 text-center font-[inherit] text-xs text-ns-text"
                      >
                        {key}
                      </kbd>
                    ))}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </dialog>
  );
}
