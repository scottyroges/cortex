/**
 * TypeScript types for the Cortex browser.
 * Mirrors src/browser/models.py
 */

export interface Stats {
  total_documents: number
  by_repository: Record<string, number>
  by_type: Record<string, number>
  by_language: Record<string, number>
}

export interface DocumentSummary {
  id: string
  doc_type: string
  repository: string
  title?: string
  created_at?: string
  updated_at?: string
  status?: string
  initiative_name?: string
  last_validation_result?: string
}

export interface Document {
  id: string
  content: string
  metadata: Record<string, unknown>
  has_embedding: boolean
}

export interface SearchResultScores {
  rrf?: number
  rerank?: number
  vector_distance?: number
  bm25?: number
}

export interface SearchResult {
  id: string
  content_preview: string
  metadata: Record<string, unknown>
  scores: SearchResultScores
}

export interface SearchResponse {
  query: string
  results: SearchResult[]
  timing_ms: number
  result_count: number
}

export type DocType = 'note' | 'insight' | 'commit' | 'initiative'

export function getDocType(metadata: Record<string, unknown>): DocType {
  const type = metadata.type as string
  if (['note', 'insight', 'commit', 'initiative'].includes(type)) {
    return type as DocType
  }
  return 'note'
}

export function getTitle(metadata: Record<string, unknown>): string | undefined {
  return metadata.title as string | undefined
}

export function getBestScore(scores: SearchResultScores): number {
  if (scores.rerank !== undefined) return scores.rerank
  if (scores.rrf !== undefined) return scores.rrf
  return 0
}

// Cleanup and Purge types

export interface CleanupRequest {
  repository: string
  path: string
  dry_run: boolean
}

export interface OrphanedResult {
  count: number
  deleted: number
  orphaned_files?: string[]
  orphaned_ids?: string[]
  error?: string
}

export interface CleanupResult {
  success: boolean
  repository: string
  dry_run: boolean
  orphaned_file_metadata: OrphanedResult
  orphaned_insights: OrphanedResult
  orphaned_dependencies: OrphanedResult
  total_orphaned: number
  total_deleted: number
}

export interface PurgeFilters {
  repository?: string
  branch?: string
  doc_type?: string
  before_date?: string
  after_date?: string
}

export interface PurgeRequest extends PurgeFilters {
  dry_run: boolean
}

export interface PurgeResult {
  success: boolean
  dry_run: boolean
  matched_count: number
  deleted_count: number
  sample_ids: string[]
  filters_applied: PurgeFilters
  error?: string
}
