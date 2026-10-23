// @ts-check
const fs = require('node:fs');
const path = require('node:path');
const matter = require('gray-matter');

/**
 * Parse a `vMAJOR.MINOR.PATCH` filename slug into a tuple suitable for
 * descending semver sort. Non-numeric or malformed parts fall back to 0.
 * Returns `[0, 0, 0]` for slugs that don't match so they sort last.
 *
 * @param {string} slug
 * @returns {[number, number, number]}
 */
function parseSemver(slug) {
  const m = /^v(\d+)\.(\d+)\.(\d+)/.exec(slug);
  if (!m) return [0, 0, 0];
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

/**
 * Reads `web/docs/release-notes/v*.mdx` at build time and exposes the
 * frontmatter (title / date / summaryHtml) as Docusaurus global data, sorted
 * newest-first by semver parsed from the filename. The release-notes index
 * page renders from this list, so the per-version pages remain the single
 * source of truth and adding a release needs only a new file.
 *
 * `summary` is treated as markdown (typically a `- ` bullet list) and
 * pre-rendered to HTML here so the React component can inject it directly.
 *
 * @typedef {{
 *   slug: string;
 *   title: string;
 *   date: string;
 *   summaryHtml: string;
 * }} ReleaseEntry
 *
 * @param {import('@docusaurus/types').LoadContext} context
 * @returns {import('@docusaurus/types').Plugin<ReleaseEntry[]>}
 */
function releaseNotesDataPlugin(context) {
  const dir = path.join(context.siteDir, 'docs', 'release-notes');

  return {
    name: 'release-notes-data',

    async loadContent() {
      if (!fs.existsSync(dir)) return [];
      // unified/remark/rehype are ESM-only; load lazily so the CJS plugin works.
      const {unified} = await import('unified');
      const {default: remarkParse} = await import('remark-parse');
      const {default: remarkMath} = await import('remark-math');
      const {default: remarkRehype} = await import('remark-rehype');
      const {default: rehypeKatex} = await import('rehype-katex');
      const {default: rehypeStringify} = await import('rehype-stringify');

      const processor = unified()
        .use(remarkParse)
        .use(remarkMath)
        .use(remarkRehype)
        .use(rehypeKatex)
        .use(rehypeStringify);

      const files = fs
        .readdirSync(dir)
        .filter((/** @type {string} */ f) => /^v.*\.mdx?$/.test(f));

      const entries = files.map((/** @type {string} */ file) => {
        const raw = fs.readFileSync(path.join(dir, file), 'utf-8');
        const {data} = matter(raw);
        // YAML may parse `2026-05-04` as a Date; normalize to ISO yyyy-mm-dd.
        let date = '';
        if (data.date instanceof Date) {
          date = data.date.toISOString().slice(0, 10);
        } else if (typeof data.date === 'string') {
          date = data.date;
        }
        const summarySrc = String(data.summary ?? '').trim();
        const summaryHtml = summarySrc
          ? String(processor.processSync(summarySrc))
          : '';
        const slug = file.replace(/\.mdx?$/, '');
        return {
          slug,
          title: String(data.title ?? slug),
          date,
          summaryHtml,
        };
      });

      // Sort by semver descending so the newest release is first.
      entries.sort((a, b) => {
        const av = parseSemver(a.slug);
        const bv = parseSemver(b.slug);
        for (let i = 0; i < 3; i++) {
          if (av[i] !== bv[i]) return bv[i] - av[i];
        }
        return 0;
      });
      return entries;
    },

    async contentLoaded({content, actions}) {
      actions.setGlobalData(content);
    },

    getPathsToWatch() {
      return [path.join(dir, '*.mdx'), path.join(dir, '*.md')];
    },
  };
}

module.exports = releaseNotesDataPlugin;
