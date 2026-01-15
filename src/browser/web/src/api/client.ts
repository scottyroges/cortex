/**
 * API client for Cortex browse endpoints.
 * Mirrors src/browser/client.py
 */

import type { Stats, DocumentSummary, Document, SearchResponse } from '../types'

/**
 * Generate a readable display title from document metadata.
 */
function generateDisplayTitle(metadata: Record<string, unknown>): string | undefined {
  // Use explicit title if available
  if (metadata.title && typeof metadata.title === 'string') {
    return metadata.title
  }

  // For code documents, extract filename from file_path
  if (metadata.type === 'code' && metadata.file_path) {
    const filePath = metadata.file_path as string
    // Extract relative path after common prefixes
    const patterns = ['/Projects/', '/src/', '/Users/']
    for (const pattern of patterns) {
      const idx = filePath.lastIndexOf(pattern)
      if (idx !== -1 && pattern === '/Projects/') {
        // For /Projects/, take everything after the repo name
        const afterProjects = filePath.slice(idx + pattern.length)
        const slashIdx = afterProjects.indexOf('/')
        if (slashIdx !== -1) {
          return afterProjects.slice(slashIdx + 1)
        }
      }
    }
    // Fallback: just the filename
    const lastSlash = filePath.lastIndexOf('/')
    if (lastSlash !== -1) {
      return filePath.slice(lastSlash + 1)
    }
    return filePath
  }

  // For commits, use summary preview
  if (metadata.type === 'commit' && metadata.summary) {
    const summary = metadata.summary as string
    return summary.length > 60 ? summary.slice(0, 60) + '...' : summary
  }

  // For initiatives, use name
  if (metadata.type === 'initiative' && metadata.name) {
    return metadata.name as string
  }

  return undefined
}

export class CortexClientError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'CortexClientError'
  }
}

export class DaemonNotRunningError extends CortexClientError {
  constructor() {
    super('Cannot connect to Cortex daemon. Is it running?')
    this.name = 'DaemonNotRunningError'
  }
}

export class APIError extends CortexClientError {
  constructor(
    public status: number,
    message: string
  ) {
    super(message)
    this.name = 'APIError'
  }
}

export class CortexClient {
  private baseUrl: string

  constructor(baseUrl = '') {
    this.baseUrl = baseUrl
  }

  private async request<T>(path: string, params?: Record<string, string>): Promise<T> {
    const url = new URL(path, this.baseUrl || window.location.origin)
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== '') {
          url.searchParams.set(key, value)
        }
      })
    }

    try {
      const response = await fetch(url.toString())
      if (!response.ok) {
        throw new APIError(response.status, `API error: ${response.statusText}`)
      }
      return await response.json()
    } catch (error) {
      if (error instanceof APIError) throw error
      if (error instanceof TypeError && error.message.includes('Failed to fetch')) {
        throw new DaemonNotRunningError()
      }
      throw new CortexClientError(String(error))
    }
  }

  async healthCheck(): Promise<boolean> {
    try {
      await this.request('/health')
      return true
    } catch {
      return false
    }
  }

  async getStats(): Promise<Stats> {
    return this.request('/browse/stats')
  }

  async listDocuments(params: {
    repository?: string
    doc_type?: string
    limit?: number
  } = {}): Promise<DocumentSummary[]> {
    const response = await this.request<{ documents: Array<{ id: string; metadata: Record<string, unknown> }> }>(
      '/browse/list',
      {
        repository: params.repository || '',
        type: params.doc_type || '',
        limit: params.limit?.toString() || '',
      }
    )

    return response.documents.map((doc) => ({
      id: doc.id,
      doc_type: (doc.metadata.type as string) || 'unknown',
      repository: (doc.metadata.repository as string) || 'unknown',
      title: generateDisplayTitle(doc.metadata),
      created_at: doc.metadata.created_at as string | undefined,
      status: doc.metadata.status as string | undefined,
      initiative_name: doc.metadata.initiative_name as string | undefined,
      last_validation_result: doc.metadata.last_validation_result as string | undefined,
    }))
  }

  async getDocument(docId: string): Promise<Document> {
    return this.request('/browse/get', { id: docId })
  }

  async search(
    query: string,
    params: { limit?: number; rerank?: boolean } = {}
  ): Promise<SearchResponse> {
    const response = await this.request<{
      query: string
      results: Array<{
        id: string
        content_preview: string
        metadata: Record<string, unknown>
        scores: {
          rrf?: number
          rerank?: number
          vector_distance?: number
          bm25?: number
        }
      }>
      timing: { total_ms: number }
      result_count: number
    }>('/browse/search', {
      q: query,
      limit: params.limit?.toString() || '',
      rerank: params.rerank ? 'true' : '',
    })

    return {
      query: response.query,
      results: response.results.map((r) => ({
        id: r.id,
        content_preview: r.content_preview,
        metadata: r.metadata,
        scores: r.scores,
      })),
      timing_ms: response.timing?.total_ms || 0,
      result_count: response.result_count,
    }
  }
}

export const client = new CortexClient()
