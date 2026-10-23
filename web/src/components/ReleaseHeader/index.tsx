import {useDoc} from '@docusaurus/plugin-content-docs/client';
import React from 'react';

const REPO_URL = 'https://github.com/epistorm/epydemix-webapi';

// YAML parses unquoted `2026-05-04` as a JS Date. Render as plain
// `YYYY-MM-DD` regardless of whether frontmatter passed a Date or a string.
function formatDate(raw: unknown): string {
  if (!raw) return '';
  if (raw instanceof Date) {
    return raw.toISOString().slice(0, 10);
  }
  return String(raw);
}

export default function ReleaseHeader() {
  const {frontMatter} = useDoc();
  const version = String(frontMatter.title ?? '');
  const date = formatDate((frontMatter as Record<string, unknown>).date);
  if (!version) return null;

  const releaseUrl = `${REPO_URL}/releases/tag/${version}`;
  return (
    <p>
      {date && <>Released {date} · </>}
      <a href={releaseUrl} target="_blank" rel="noopener noreferrer">
        GitHub Release
      </a>
    </p>
  );
}
