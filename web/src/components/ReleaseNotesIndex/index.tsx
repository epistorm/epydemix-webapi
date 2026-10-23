import Link from '@docusaurus/Link';
import {usePluginData} from '@docusaurus/useGlobalData';
import React from 'react';

interface ReleaseEntry {
  slug: string;
  title: string;
  date: string;
  summaryHtml: string;
  sidebarPosition: number;
}

/**
 * Renders the list of releases on the release-notes index page from the
 * global data published by the `release-notes-data` Docusaurus plugin.
 *
 * `summaryHtml` is the markdown summary already rendered to HTML at build
 * time by the plugin (via micromark), so we inject it directly.
 */
export default function ReleaseNotesIndex() {
  const entries = usePluginData('release-notes-data') as ReleaseEntry[] | undefined;
  if (!entries || entries.length === 0) return null;

  return (
    <>
      {entries.map((entry) => (
        <section key={entry.slug}>
          <h3>
            <Link to={`./${entry.slug}`}>{entry.title}</Link>
            {entry.date && <> ({entry.date})</>}
          </h3>
          {entry.summaryHtml && (
            <div dangerouslySetInnerHTML={{__html: entry.summaryHtml}} />
          )}
        </section>
      ))}
    </>
  );
}
