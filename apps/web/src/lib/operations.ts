export interface Freshness { checked_at: number | null; error: string | null; stale: boolean }
export interface Repository { name: string; description: string | null; url: string; private: boolean; archived: boolean; branch: string; updated_at: string }
export interface Repositories extends Freshness { repos: Repository[]; limited: boolean }
export interface GithubItem { number: number; title: string; user: string; updated_at: string; draft: boolean; labels: string[]; url: string }
export interface GithubStream extends Freshness { items?: GithubItem[]; limited?: boolean }
export interface RepositoryDetails { name: string; pulls: GithubStream; issues: GithubStream }
export interface Report { id: string; name: string; size: number; modified_at: number; readable: boolean; source?: string; source_id?: string; title?: string }
export interface Reports { reports: Report[]; available: boolean; error: string | null; limited: boolean; root: string }
export interface ReportContent extends Report { content: string; format: 'text' | 'markdown'; response_only?: boolean }
export function dateLabel(value: number | string | null): string {
  if (value === null) return 'Not checked yet'
  const date = new Date(typeof value === 'number' ? value * 1000 : value)
  return Number.isNaN(date.getTime()) ? 'Not reported' : date.toLocaleString()
}
export function bytesLabel(bytes: number): string { return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KiB` }
