import React from 'react';
import clsx from 'clsx';
import {translate} from '@docusaurus/Translate';
import styles from './styles.module.css';

type Props = {
  onClick: React.MouseEventHandler<HTMLButtonElement>;
};

export default function CollapseButton({onClick}: Props): React.ReactElement {
  const label = translate({
    id: 'theme.docs.sidebar.collapseButtonTitle',
    message: 'Collapse sidebar',
    description: 'The title attribute for collapse button of doc sidebar',
  });
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      className={clsx(styles.collapseSidebarButton)}
      onClick={onClick}>
      {/* lucide: panel-left-close */}
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
        <path d="m16 15-3-3 3-3" />
      </svg>
    </button>
  );
}
