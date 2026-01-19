<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { Stats, DocumentSummary, SearchResult } from './types'
import { client } from './api/client'
import StatsPanel from './components/StatsPanel.vue'
import DocumentList from './components/DocumentList.vue'
import DocumentDetail from './components/DocumentDetail.vue'
import SearchPanel from './components/SearchPanel.vue'

const stats = ref<Stats | null>(null)
const selectedDoc = ref<DocumentSummary | null>(null)
const connected = ref(true)
const loading = ref(true)
const documentListRef = ref<InstanceType<typeof DocumentList> | null>(null)

// Filter state (controlled by StatsPanel, consumed by DocumentList)
const typeFilter = ref<string | null>(null)
const repoFilter = ref<string | null>(null)

function onFilterType(type: string | null) {
  typeFilter.value = type
}

function onFilterRepo(repo: string | null) {
  repoFilter.value = repo
}

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

function onDocumentDeleted() {
  selectedDoc.value = null
  documentListRef.value?.refresh()
  loadStats() // Refresh stats counts
}

function onDocumentUpdated() {
  documentListRef.value?.refresh()
}

function onSelectDocument(doc: DocumentSummary) {
  selectedDoc.value = doc
}

function onSelectSearchResult(result: SearchResult) {
  selectedDoc.value = {
    id: result.id,
    doc_type: (result.metadata.type as string) || 'unknown',
    repository: (result.metadata.repository as string) || 'unknown',
    title: result.metadata.title as string | undefined,
    created_at: result.metadata.created_at as string | undefined,
  }
}

onMounted(loadStats)
</script>

<template>
  <div class="h-screen flex flex-col bg-gray-900">
    <!-- Header -->
    <header class="bg-gray-800 border-b border-gray-700 px-4 py-3 flex-shrink-0">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <svg class="w-8 h-8 text-blue-500" viewBox="0 0 100 100">
            <circle cx="50" cy="50" r="45" fill="currentColor" />
            <circle cx="50" cy="50" r="20" fill="#1e293b" />
            <circle cx="50" cy="50" r="8" fill="#60a5fa" />
          </svg>
          <h1 class="text-xl font-semibold text-gray-100">Cortex Memory Browser</h1>
        </div>
        <div class="flex items-center gap-2">
          <span
            class="w-2 h-2 rounded-full"
            :class="connected ? 'bg-green-500' : 'bg-red-500'"
          ></span>
          <span class="text-sm text-gray-400">
            {{ connected ? 'Connected' : 'Disconnected' }}
          </span>
        </div>
      </div>
    </header>

    <!-- Loading State -->
    <div v-if="loading" class="flex-1 flex items-center justify-center text-gray-400">
      Loading...
    </div>

    <!-- Disconnected State -->
    <div
      v-else-if="!connected"
      class="flex-1 flex items-center justify-center"
    >
      <div class="text-center">
        <div class="text-red-400 text-lg mb-2">Cannot connect to Cortex daemon</div>
        <p class="text-gray-500 text-sm">
          Make sure the Cortex daemon is running with HTTP enabled.
        </p>
        <button class="btn btn-primary mt-4" @click="loadStats">Retry</button>
      </div>
    </div>

    <!-- Main Content -->
    <div v-else class="flex-1 flex overflow-hidden">
      <!-- Left Sidebar: Stats -->
      <aside class="w-56 flex-shrink-0 border-r border-gray-700 overflow-auto">
        <StatsPanel
          :active-type-filter="typeFilter"
          :active-repo-filter="repoFilter"
          @filter-type="onFilterType"
          @filter-repo="onFilterRepo"
        />
      </aside>

      <!-- Main Area -->
      <main class="flex-1 flex flex-col overflow-hidden">
        <!-- Top: Document List & Detail -->
        <div class="flex-1 flex overflow-hidden">
          <!-- Document List -->
          <div class="w-80 flex-shrink-0 border-r border-gray-700">
            <DocumentList
              ref="documentListRef"
              :stats="stats"
              :type-filter="typeFilter"
              :repo-filter="repoFilter"
              @select="onSelectDocument"
            />
          </div>

          <!-- Document Detail -->
          <div class="flex-1">
            <DocumentDetail
              :summary="selectedDoc"
              @document-deleted="onDocumentDeleted"
              @document-updated="onDocumentUpdated"
            />
          </div>
        </div>

        <!-- Bottom: Search -->
        <div class="flex-shrink-0 border-t border-gray-700">
          <SearchPanel @select-result="onSelectSearchResult" />
        </div>
      </main>
    </div>
  </div>
</template>
