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
 * The write-up arrives as "**TL;DR:** verdict", "## Key Points" bullets and "## Risk Considerations"
 * bullets (owner report 2026-10-06). Older write-ups are one long paragraph: those become a headline
 * and up to 4 sentences, dropping sentences about entries, stops and targets (the plan block shows them).
 */
export function parseNote(text: string): {headline: string; points: string[]; risks: string[]} {
  const clean = text.replace(/\*\*/g, '').replace(/\r/g, '');
  const parts = clean.split(/^#{1,3}\s+(.+)$/m);
  const bullets = (body: string) => body.split('\n').map(l => l.trim()).filter(l => /^[-•*]\s+/.test(l)).map(l => l.replace(/^[-•*]\s+/, ''));
  if (parts.length > 1) {
    const headline = parts[0].replace(/^\s*TL;?DR\s*:?\s*/i, '').replace(/\s+/g, ' ').trim();
    let points: string[] = [], risks: string[] = [];
    for (let i = 1; i < parts.length; i += 2) {
      const name = parts[i].toLowerCase(), body = parts[i + 1] || '';
      if (name.includes('risk')) risks = risks.concat(bullets(body));
      else points = points.concat(bullets(body));
    }
    return {headline, points: points.slice(0, 5), risks: risks.slice(0, 3)};
  }
  const flat = clean.replace(/^\s*TL;?DR\s*:?\s*/i, '').replace(/\s+/g, ' ').trim();
  const sentences = flat.split(/(?<=[.!?])\s+(?=[A-Z$"(])/).map(s => s.trim()).filter(Boolean);
  const headline = sentences.shift() || '';
  const planWords = /\b(buy zone|entry|stop[- ]loss|stop|targets?|risk[- ]reward|price target)\b/i;
  return {headline, points: sentences.filter(s => !planWords.test(s) && s.length > 20).slice(0, 4), risks: []};
}
