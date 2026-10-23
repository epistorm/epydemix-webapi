import React from 'react';
import type { ApiMode } from '../constants';

type Props = {
  mode: ApiMode;
  customUrl: string;
  onModeChange: (mode: ApiMode) => void;
  onCustomUrlChange: (url: string) => void;
};

export default function ApiPicker({ mode, customUrl, onModeChange, onCustomUrlChange }: Props) {
  return (
    <>
      <label htmlFor="api">API:</label>
      <select id="api" value={mode} onChange={(e) => onModeChange(e.target.value as ApiMode)}>
        <option value="production">Production</option>
        <option value="custom">Custom</option>
      </select>
      {mode === 'custom' && (
        <input
          type="url"
          value={customUrl}
          onChange={(e) => onCustomUrlChange(e.target.value)}
          placeholder="http://localhost:8000"
          style={{ minWidth: '220px', flex: 1 }}
        />
      )}
    </>
  );
}
