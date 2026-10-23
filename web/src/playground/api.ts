import type { ShowKey, SimulationResponse } from './types';

export async function runSimulation(
  apiBase: string,
  body: unknown,
): Promise<SimulationResponse> {
  const res = await fetch(`${apiBase}/api/v1/simulations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${text.slice(0, 500)}`);
  }
  return JSON.parse(text) as SimulationResponse;
}

export function pickSeries(
  response: SimulationResponse,
  show: ShowKey,
  ageGroup: string,
  quantile = '0.5',
): number[] | null {
  const results = response.results;
  if (!results) return null;
  if (show.kind === 'parameter') {
    const series = results.parameters?.data?.[show.name]?.[ageGroup];
    return Array.isArray(series) ? series : null;
  }
  const bucket = show.kind === 'compartment' ? results.compartments : results.transitions;
  const series = bucket?.data?.[show.name]?.[ageGroup]?.[quantile];
  return Array.isArray(series) ? series : null;
}

export function listShowKeys(response: SimulationResponse): ShowKey[] {
  const out: ShowKey[] = [];
  const c = response.results?.compartments?.data;
  if (c) for (const name of Object.keys(c)) out.push({ kind: 'compartment', name });
  const t = response.results?.transitions?.data;
  if (t) for (const name of Object.keys(t)) out.push({ kind: 'transition', name });
  const p = response.results?.parameters?.data;
  if (p) for (const name of Object.keys(p)) out.push({ kind: 'parameter', name });
  return out;
}

export function listAgeGroups(response: SimulationResponse, show?: ShowKey | null): string[] {
  const r = response.results;
  if (!r) return [];
  if (show?.kind === 'parameter') {
    const entry = r.parameters?.data?.[show.name];
    return entry ? Object.keys(entry) : [];
  }
  if (show?.kind === 'transition') {
    const entry = r.transitions?.data?.[show.name];
    if (entry) return Object.keys(entry);
  }
  if (show?.kind === 'compartment') {
    const entry = r.compartments?.data?.[show.name];
    if (entry) return Object.keys(entry);
  }
  // Fallback: any compartment, else any transition, else any parameter.
  const first =
    (r.compartments?.data && Object.values(r.compartments.data)[0]) ||
    (r.transitions?.data && Object.values(r.transitions.data)[0]) ||
    (r.parameters?.data && Object.values(r.parameters.data)[0]);
  return first ? Object.keys(first) : [];
}

export function pickDates(response: SimulationResponse, show?: ShowKey | null): string[] | null {
  const r = response.results;
  if (!r) return null;
  if (show?.kind === 'parameter' && r.parameters?.dates) return r.parameters.dates;
  return r.compartments?.dates ?? r.transitions?.dates ?? r.parameters?.dates ?? null;
}

export function showKeyId(s: ShowKey): string {
  return `${s.kind}:${s.name}`;
}

// Strip // line comments and /* ... */ block comments while preserving string contents.
export function stripJsonComments(input: string): string {
  let out = '';
  let i = 0;
  const n = input.length;
  while (i < n) {
    const c = input[i];
    if (c === '"') {
      out += c;
      i++;
      while (i < n) {
        const ch = input[i];
        out += ch;
        i++;
        if (ch === '\\' && i < n) {
          out += input[i];
          i++;
          continue;
        }
        if (ch === '"') break;
      }
      continue;
    }
    if (c === '/' && input[i + 1] === '/') {
      while (i < n && input[i] !== '\n') i++;
      continue;
    }
    if (c === '/' && input[i + 1] === '*') {
      i += 2;
      while (i < n && !(input[i] === '*' && input[i + 1] === '/')) i++;
      i = Math.min(i + 2, n);
      continue;
    }
    out += c;
    i++;
  }
  return out;
}

export function parseShowKeyId(id: string): ShowKey | null {
  const i = id.indexOf(':');
  if (i < 0) return null;
  const kind = id.slice(0, i);
  if (kind !== 'compartment' && kind !== 'transition' && kind !== 'parameter') return null;
  return { kind, name: id.slice(i + 1) };
}
