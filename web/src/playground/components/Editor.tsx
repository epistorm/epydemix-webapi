import React, { useEffect, useRef } from 'react';
import MonacoEditor, { type OnMount, loader } from '@monaco-editor/react';
import { useColorMode } from '@docusaurus/theme-common';

type Props = {
  value: string;
  onChange: (next: string) => void;
};

const SCHEMA_URI = 'inmemory://schema/simulation-request.json';
const MODEL_URI = 'inmemory://model/simulation-request.json';
const MONACO_CDN = 'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.0/min';

let schemaRegistered = false;
let workerShimInstalled = false;

// Web workers can't be loaded directly from a different origin, so wrap the
// CDN worker in a same-origin Blob that imports it via `importScripts`.
function installWorkerShim() {
  if (workerShimInstalled || typeof window === 'undefined') return;
  workerShimInstalled = true;
  (window as any).MonacoEnvironment = {
    getWorkerUrl: () => {
      const src = `self.MonacoEnvironment = { baseUrl: '${MONACO_CDN}/' };\n` +
        `importScripts('${MONACO_CDN}/vs/base/worker/workerMain.js');`;
      return URL.createObjectURL(new Blob([src], { type: 'text/javascript' }));
    },
  };
}

async function ensureSchema(monaco: Parameters<OnMount>[1]) {
  if (schemaRegistered) return;
  try {
    const res = await fetch('/openapi.json');
    if (!res.ok) return;
    const spec = await res.json();
    const components = spec?.components;
    const simReq = components?.schemas?.SimulationRequest;
    if (!simReq) return;
    const schema = {
      ...simReq,
      // Embed components so $refs of the form #/components/schemas/X resolve
      // when Monaco walks the schema document.
      components,
    };
    monaco.languages.json.jsonDefaults.setDiagnosticsOptions({
      validate: true,
      allowComments: true,
      schemas: [
        {
          uri: SCHEMA_URI,
          fileMatch: [MODEL_URI],
          schema,
        },
      ],
    });
    schemaRegistered = true;
  } catch {
    // Schema completion is best-effort; ignore failures.
  }
}

export default function Editor({ value, onChange }: Props) {
  const { colorMode } = useColorMode();
  const monacoRef = useRef<Parameters<OnMount>[1] | null>(null);

  // Install the worker shim before Monaco starts loading, then point the AMD
  // loader at the same CDN version.
  useEffect(() => {
    installWorkerShim();
    loader.config({ paths: { vs: `${MONACO_CDN}/vs` } });
  }, []);

  const handleMount: OnMount = (_editor, monaco) => {
    monacoRef.current = monaco;
    void ensureSchema(monaco);
  };

  return (
    <MonacoEditor
      height="100%"
      language="json"
      path={MODEL_URI}
      value={value}
      onChange={(v) => onChange(v ?? '')}
      onMount={handleMount}
      theme={colorMode === 'dark' ? 'vs-dark' : 'light'}
      options={{
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        fontSize: 13,
        tabSize: 2,
        formatOnPaste: true,
        automaticLayout: true,
        wordWrap: 'on',
        wrappingIndent: 'indent',
      }}
    />
  );
}
