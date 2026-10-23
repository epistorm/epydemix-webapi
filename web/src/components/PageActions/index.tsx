import BrowserOnly from '@docusaurus/BrowserOnly';
import {useLocation} from '@docusaurus/router';
import React, {useEffect, useRef, useState} from 'react';
import styles from './styles.module.css';

const CHAT_TARGETS = [
  {
    id: 'claude',
    label: 'Open in Claude',
    href: (url: string) =>
      `https://claude.ai/new?q=${encodeURIComponent(`I'd like to discuss the content from ${url}`)}`,
  },
  {
    id: 'chatgpt',
    label: 'Open in ChatGPT',
    href: (url: string) =>
      `https://chatgpt.com/?q=${encodeURIComponent(`I'd like to discuss the content from ${url}`)}`,
  },
];

const COPY_ICON = (
  <svg className={styles.icon} viewBox="0 0 24 24" aria-hidden="true">
    <path d="M19 21H8V7h11m0-2H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2m-3-4H4a2 2 0 0 0-2 2v14h2V3h12V1Z" />
  </svg>
);

const CHEVRON_ICON = (
  <svg className={styles.icon} viewBox="0 0 24 24" aria-hidden="true">
    <path d="M7.41 8.58 12 13.17l4.59-4.59L18 10l-6 6-6-6 1.41-1.42Z" />
  </svg>
);

const EXTERNAL_ICON = (
  <svg className={styles.iconSmall} viewBox="0 0 24 24" aria-hidden="true">
    <path d="M14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3m-2 16H5V5h7V3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7h-2v7Z" />
  </svg>
);

function pageMarkdownUrl(pathname: string): string {
  // Strip trailing slash, append .md. Docusaurus serves /docs/foo, mirrors live at /docs/foo.md.
  const clean = pathname.replace(/\/+$/, '');
  return `${clean}.md`;
}

function PageActionsInner() {
  const {pathname} = useLocation();
  const mdUrl = pageMarkdownUrl(pathname);
  const pageUrl =
    typeof window !== 'undefined'
      ? `${window.location.origin}${pathname.replace(/\/+$/, '')}`
      : '';

  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'error'>('idle');
  const [menuOpen, setMenuOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Close the menu when clicking outside.
  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [menuOpen]);

  async function copyMarkdown(): Promise<boolean> {
    try {
      const res = await fetch(mdUrl);
      if (!res.ok) throw new Error(`fetch failed: ${res.status}`);
      const text = await res.text();
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      console.error('PageActions copy failed:', e);
      return false;
    }
  }

  async function handleCopyClick() {
    const ok = await copyMarkdown();
    setCopyState(ok ? 'copied' : 'error');
    window.setTimeout(() => setCopyState('idle'), 2000);
  }

  function handleChatClick() {
    // Fire-and-forget the clipboard copy so the user can paste the markdown
    // if the assistant can't fetch the URL itself. Don't `await` — the
    // navigation must happen synchronously in the click handler, otherwise
    // the browser drops the user gesture and silently blocks the popup
    // (this is what was killing the Vercel build vs. localhost: CDN latency
    // pushed the navigation past the gesture window).
    void copyMarkdown();
    setMenuOpen(false);
  }

  return (
    <div className={styles.combo} ref={wrapperRef}>
      <button
        type="button"
        className={styles.copyZone}
        onClick={handleCopyClick}
        aria-label="Copy this page as markdown"
      >
        {COPY_ICON}
        <span className={styles.label}>
          {copyState === 'copied' ? 'Copied!' : copyState === 'error' ? 'Copy failed' : 'Copy page'}
        </span>
      </button>
      <span className={styles.separator} aria-hidden="true" />
      <button
        type="button"
        className={styles.arrowZone}
        onClick={() => setMenuOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        aria-label="Open page actions menu"
      >
        {CHEVRON_ICON}
      </button>
      {menuOpen && (
        <div className={styles.menu} role="menu">
          <a
            className={styles.menuItem}
            href={mdUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => setMenuOpen(false)}
            role="menuitem"
          >
            {EXTERNAL_ICON}
            <span>Open Markdown</span>
          </a>
          {CHAT_TARGETS.map((t) => (
            <a
              key={t.id}
              className={styles.menuItem}
              href={t.href(pageUrl)}
              target="_blank"
              rel="noopener noreferrer"
              onClick={handleChatClick}
              role="menuitem"
            >
              {EXTERNAL_ICON}
              <span>{t.label}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

export default function PageActions() {
  return <BrowserOnly>{() => <PageActionsInner />}</BrowserOnly>;
}
