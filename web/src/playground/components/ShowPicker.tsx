import React from 'react';
import type { ShowKey } from '../types';
import { parseShowKeyId, showKeyId } from '../api';

type Props = {
  options: ShowKey[];
  value: ShowKey | null;
  onChange: (next: ShowKey) => void;
};

export default function ShowPicker({ options, value, onChange }: Props) {
  const compartments = options.filter((o) => o.kind === 'compartment');
  const transitions = options.filter((o) => o.kind === 'transition');
  const parameters = options.filter((o) => o.kind === 'parameter');

  return (
    <select
      value={value ? showKeyId(value) : ''}
      onChange={(e) => {
        const parsed = parseShowKeyId(e.target.value);
        if (parsed) onChange(parsed);
      }}
      disabled={options.length === 0}
    >
      {options.length === 0 && <option value="">(run a simulation first)</option>}
      {compartments.length > 0 && (
        <optgroup label="Compartments">
          {compartments.map((o) => (
            <option key={showKeyId(o)} value={showKeyId(o)}>
              {o.name}
            </option>
          ))}
        </optgroup>
      )}
      {transitions.length > 0 && (
        <optgroup label="Transitions">
          {transitions.map((o) => (
            <option key={showKeyId(o)} value={showKeyId(o)}>
              {o.name}
            </option>
          ))}
        </optgroup>
      )}
      {parameters.length > 0 && (
        <optgroup label="Parameters">
          {parameters.map((o) => (
            <option key={showKeyId(o)} value={showKeyId(o)}>
              {o.name}
            </option>
          ))}
        </optgroup>
      )}
    </select>
  );
}
