import React from 'react';
import Layout from '@theme/Layout';
import styles from '../playground/Playground.module.css';
import SimulationsPlayground from '../playground/SimulationsPlayground';

export default function PlaygroundPage() {
  return (
    <Layout
      title="Playground"
      description="Interactive playground for the epydemix Web API"
      noFooter
    >
      <div className={styles.page}>
        <SimulationsPlayground />
      </div>
    </Layout>
  );
}
