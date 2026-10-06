/** Display helpers shared by cards and the ticker report. */
export function money(value: number | null | undefined): string {
  if (value == null) return '—';
  return '$' + value.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

export function compact(value: number | null | undefined): string {
  if (value == null) return '—';
  return Intl.NumberFormat('en-US', {notation: 'compact', maximumFractionDigits: 1}).format(value);
}

export function timeAgo(epoch: number | null | undefined, now = Date.now() / 1000): string {
  if (epoch == null) return '';
  const s = Math.max(0, now - epoch);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return Math.floor(s / 86400) + 'd ago';
}

/** "@handle" from an x.com / twitter.com post link; the source name from other links. */
export function sourceLabel(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^www\./, '');
    if (host === 'x.com' || host === 'twitter.com') {
      const handle = u.pathname.split('/').filter(Boolean)[0];
      return handle ? '@' + handle : 'X';
    }
    if (host.includes('youtube') || host === 'youtu.be') return 'YouTube';
    if (host.includes('reddit')) return 'Reddit';
    return host;
  } catch { return null; }
}

/**
 * The AI write-up arrives as markdown-ish prose ("**TL;DR:** ..." + a long paragraph).
 * Show it as one headline and a few short points. Sentences about entries, stops and
 * targets are dropped: the trade plan block shows those numbers.
 */
export function summarize(text: string): {headline: string; points: string[]} {
  const clean = text.replace(/\*\*/g, '').replace(/^\s*(TL;?DR)\s*:?\s*/i, '').replace(/\s+/g, ' ').trim();
  const sentences = clean.split(/(?<=[.!?])\s+(?=[A-Z$"(])/).map(s => s.trim()).filter(Boolean);
  const headline = sentences.shift() || '';
  const planWords = /\b(buy zone|entry|stop[- ]loss|stop|targets?|risk[- ]reward|price target)\b/i;
  const points = sentences.filter(s => !planWords.test(s) && s.length > 20).slice(0, 4);
  return {headline, points};
}
