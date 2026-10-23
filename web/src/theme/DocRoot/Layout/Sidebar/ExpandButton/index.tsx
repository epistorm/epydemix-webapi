import React from 'react';
import {translate} from '@docusaurus/Translate';
import styles from './styles.module.css';

type Props = {
  toggleSidebar: () => void;
};

export default function DocRootLayoutSidebarExpandButton({
  toggleSidebar,
}: Props): React.ReactElement {
  const label = translate({
    id: 'theme.docs.sidebar.expandButtonTitle',
    message: 'Expand sidebar',
    description:
      'The ARIA label and title attribute for expand button of doc sidebar',
  });
  return (
    <button
      type="button"
      className={styles.expandButton}
      title={label}
      aria-label={label}
      onClick={toggleSidebar}>
      {/* lucide: panel-left-open */}
      <svg
        className={styles.icon}
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true">
        <rect width="18" height="18" x="3" y="3" rx="2" />
        <path d="M9 3v18" />
        <path d="m14 9 3 3-3 3" />
      </svg>
    </button>
  );
}
