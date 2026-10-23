// Haline-inspired palette (cmocean)
export const PALETTE = [
  '#1c79a3', // blue
  '#1ea197', // teal
  '#3fa86a', // green
  '#9bc24a', // yellow-green
  '#dccf3e', // yellow
  '#1d4894', // deep blue
  '#2a186c', // deep indigo
];

export const PRODUCTION_URL = 'https://epyscenario-api.isi.it';
export const DEFAULT_CUSTOM_URL = 'http://localhost:8000';

export const STORAGE_KEY_EDITOR = 'epydemix-playground:editor-value';
export const STORAGE_KEY_API_MODE = 'epydemix-playground:api-mode';
export const STORAGE_KEY_CUSTOM_URL = 'epydemix-playground:custom-url';

export type ApiMode = 'production' | 'custom';
