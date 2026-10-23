import React from 'react';
import OriginalContent from '@theme-original/DocItem/Content';
import PageActions from '@site/src/components/PageActions';

/**
 * Swizzle target: inject <PageActions /> above every doc page's body so users
 * can copy the page as markdown or open it in a chat assistant from anywhere.
 * The component derives the markdown URL and chat targets from the current
 * route, so no per-page configuration is needed.
 */
export default function Content(props: any): React.ReactElement {
  return (
    <>
      <PageActions />
      <OriginalContent {...props} />
    </>
  );
}
