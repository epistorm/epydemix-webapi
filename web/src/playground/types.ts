export type Quantile = string; // e.g. "0.5"

export type SeriesByAgeByQuantile = Record<string, Record<Quantile, number[]>>;

export type SeriesByAge = Record<string, number[]>;

export type SimulationResults = {
  compartments?: { data: Record<string, SeriesByAgeByQuantile>; dates?: string[] };
  transitions?: { data: Record<string, SeriesByAgeByQuantile>; dates?: string[] };
  parameters?: { data: Record<string, SeriesByAge>; dates?: string[] };
  summary?: unknown;
  trajectories?: unknown;
};

export type SimulationWarning = {
  code: 'parameter_overridden';
  parameter: string;
  overridden_by: string;
  message: string;
};

export type SimulationResponse = {
  simulation_id: string;
  status: 'completed';
  metadata?: unknown;
  results: SimulationResults;
  warnings?: SimulationWarning[];
};

export type ShowKind = 'compartment' | 'transition' | 'parameter';

export type ShowKey = {
  kind: ShowKind;
  name: string;
};

export type Run = {
  id: string;
  index: number;       // human-friendly #N
  label: string;       // e.g. "SEIHR · Italy · R0=2.5"
  color: string;
  request: unknown;    // exact body sent
  response: SimulationResponse;
};
