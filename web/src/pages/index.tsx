import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import type {ReactElement} from 'react';

export default function Home(): ReactElement {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout title={siteConfig.title} description="REST API for running epidemic simulations on epydemix">
      <main style={{display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '4rem 2rem'}}>
        <h1>{siteConfig.title}</h1>
        <p style={{fontSize: '1.2rem', color: 'var(--ifm-color-emphasis-700)', marginBottom: '2rem'}}>
          REST API for running epidemic simulations on epydemix
        </p>
        <div style={{display: 'flex', gap: '1rem'}}>
          <Link className="button button--primary button--lg" to="/docs">
            Get Started
          </Link>
          <Link className="button button--secondary button--lg" to="/api-reference">
            API Reference
          </Link>
        </div>
      </main>
    </Layout>
  );
}
