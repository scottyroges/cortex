import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Stats, DocumentSummary, SearchResult } from '../types'
import { client } from '../api/client'

export const useBrowserStore = defineStore('browser', () => {
  // Connection state
  const connected = ref(true)
  const loading = ref(true)

  // Stats
  const stats = ref<Stats | null>(null)

  // Filters
  const typeFilter = ref<string | null>(null)
  const repoFilter = ref<string | null>(null)

  // Selected document
  const selectedDoc = ref<DocumentSummary | null>(null)

  // Document list
  const documents = ref<DocumentSummary[]>([])
  const documentsLoading = ref(false)
  const documentsError = ref<string | null>(null)

  // Computed
  const repositories = computed(() =>
    stats.value ? Object.keys(stats.value.by_repository) : []
  )

  const documentTypes = computed(() =>
    stats.value ? Object.keys(stats.value.by_type) : []
  )

  const hasActiveFilters = computed(() =>
    typeFilter.value !== null || repoFilter.value !== null
  )

  // Actions
  async function loadStats() {
    try {
      stats.value = await client.getStats()
      connected.value = true
    } catch {
      connected.value = false
    } finally {
      loading.value = false
    }
  }

  async function loadDocuments() {
    documentsLoading.value = true
    documentsError.value = null
    try {
      documents.value = await client.listDocuments({
        doc_type: typeFilter.value || undefined,
        repository: repoFilter.value || undefined,
        limit: 500,
      })
    } catch (e) {
      documentsError.value = e instanceof Error ? e.message : 'Failed to load documents'
    } finally {
      documentsLoading.value = false
    }
  }

  function setTypeFilter(type: string | null) {
    typeFilter.value = type
  }

  function setRepoFilter(repo: string | null) {
    repoFilter.value = repo
  }

  function clearFilters() {
    typeFilter.value = null
    repoFilter.value = null
  }

  function selectDocument(doc: DocumentSummary | null) {
    selectedDoc.value = doc
  }

  function selectSearchResult(result: SearchResult) {
    selectedDoc.value = {
      id: result.id,
      doc_type: (result.metadata.type as string) || 'unknown',
      repository: (result.metadata.repository as string) || 'unknown',
      title: result.metadata.title as string | undefined,
      created_at: result.metadata.created_at as string | undefined,
    }
  }

  function onDocumentDeleted() {
    selectedDoc.value = null
    loadDocuments()
    loadStats()
  }

  function onDocumentUpdated() {
    loadDocuments()
  }

  async function refresh() {
    await Promise.all([loadStats(), loadDocuments()])
  }

  return {
    // State
    connected,
    loading,
    stats,
    typeFilter,
    repoFilter,
    selectedDoc,
    documents,
    documentsLoading,
    documentsError,

    // Computed
    repositories,
    documentTypes,
    hasActiveFilters,

    // Actions
    loadStats,
    loadDocuments,
    setTypeFilter,
    setRepoFilter,
    clearFilters,
    selectDocument,
    selectSearchResult,
    onDocumentDeleted,
    onDocumentUpdated,
    refresh,
  }
})
