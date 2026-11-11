import type { DealDossier, SourceCitation } from "./types";

/** Índice citation_id -> SourceCitation con todas las citas del expediente. */
export function buildCitationIndex(dossier: DealDossier, extra: SourceCitation[] = []): Map<string, SourceCitation> {
  const index = new Map<string, SourceCitation>();
  const add = (c: SourceCitation | null | undefined) => {
    if (c && !index.has(c.citation_id)) index.set(c.citation_id, c);
  };
  dossier.mapped_accounts.forEach((a) => add(a.citation));
  dossier.ebitda_adjustments.forEach((a) => add(a.citation));
  dossier.red_flags.forEach((f) => f.citations.forEach(add));
  dossier.unreadable_or_unmapped_items.forEach((u) => add(u.citation));
  const p = dossier.corporate_profile;
  [
    p.legal_name,
    p.nit,
    p.ciiu_primary,
    p.ciiu_secondary,
    p.domicile,
    p.incorporation,
    p.legal_representative,
    p.alternate_legal_representative,
    ...p.statutory_limits,
  ].forEach((f) => add(f.citation));
  p.shareholders.forEach((s) => add(s.citation));
  p.legal_proceedings.forEach((l) => add(l.citation));
  dossier.memo_citations.forEach(add);
  extra.forEach(add);
  return index;
}

/** Convierte marcadores del backend a Markdown que el renderizador transforma en badges. */
export function prepareMarkdown(markdown: string): string {
  return markdown
    .replace(/\[\[cite:([A-Za-z0-9_\-]+)\]\]/g, (_, id: string) => `[§](#cite-${id})`)
    .replace(/⟦([^⟧]+)⟧/g, (_, inner: string) => `\`${inner.trim()}\``);
}
