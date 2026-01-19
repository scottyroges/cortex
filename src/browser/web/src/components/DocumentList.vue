<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import type { DocumentSummary, Stats } from '../types'
import { client } from '../api/client'
import TypeBadge from './TypeBadge.vue'

const props = defineProps<{
  stats: Stats | null
  typeFilter: string | null
  repoFilter: string | null
}>()

const emit = defineEmits<{
  select: [doc: DocumentSummary]
}>()

const documents = ref<DocumentSummary[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const selectedId = ref<string | null>(null)

// Sort state
type SortField = 'created_at' | 'updated_at' | 'title' | 'id'
const sortBy = ref<SortField>('created_at')
const sortOrder = ref<'asc' | 'desc'>('desc')

// Computed sorted documents
const sortedDocuments = computed(() => {
  const docs = [...documents.value]
  const reverse = sortOrder.value === 'desc'

  docs.sort((a, b) => {
    let aVal: string
    let bVal: string

    if (sortBy.value === 'created_at') {
      aVal = a.created_at || ''
      bVal = b.created_at || ''
    } else if (sortBy.value === 'updated_at') {
      aVal = a.updated_at || a.created_at || ''
      bVal = b.updated_at || b.created_at || ''
    } else if (sortBy.value === 'title') {
      aVal = (a.title || a.id).toLowerCase()
      bVal = (b.title || b.id).toLowerCase()
    } else {
      aVal = a.id
      bVal = b.id
    }

    return reverse ? bVal.localeCompare(aVal) : aVal.localeCompare(bVal)
  })

  return docs
})

function toggleSortOrder() {
  sortOrder.value = sortOrder.value === 'desc' ? 'asc' : 'desc'
}

async function loadDocuments() {
  loading.value = true
  error.value = null
  try {
    documents.value = await client.listDocuments({
      doc_type: props.typeFilter || undefined,
      repository: props.repoFilter || undefined,
      limit: 500,
    })
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to load documents'
  } finally {
    loading.value = false
  }
}

function selectDocument(doc: DocumentSummary) {
  selectedId.value = doc.id
  emit('select', doc)
}

function formatTime(dateStr?: string): string {
  if (!dateStr) return ''
  try {
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return date.toLocaleDateString()
  } catch {
    return ''
  }
}

watch([() => props.typeFilter, () => props.repoFilter], loadDocuments)
onMounted(loadDocuments)

defineExpose({ refresh: loadDocuments })
</script>

<template>
  <div class="card h-full flex flex-col">
    <!-- Sort controls -->
    <div class="p-3 border-b border-gray-700 flex items-center gap-2">
      <span class="text-xs text-gray-400">Sort:</span>
      <select v-model="sortBy" class="select flex-1 text-sm">
        <option value="created_at">Created</option>
        <option value="updated_at">Updated</option>
        <option value="title">Title</option>
        <option value="id">ID</option>
      </select>
      <button
        @click="toggleSortOrder"
        class="p-1.5 hover:bg-gray-700 rounded transition-colors text-gray-400 hover:text-gray-200"
        :title="sortOrder === 'desc' ? 'Descending (newest first)' : 'Ascending (oldest first)'"
      >
        <svg v-if="sortOrder === 'desc'" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
        </svg>
        <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
        </svg>
      </button>
    </div>

    <div class="flex-1 overflow-auto">
      <div v-if="loading" class="p-4 text-gray-400">Loading...</div>

      <div v-else-if="error" class="p-4 text-red-400 text-sm">{{ error }}</div>

      <div v-else-if="sortedDocuments.length === 0" class="p-4 text-gray-500 text-sm">
        No documents found
      </div>

      <ul v-else class="divide-y divide-gray-700">
        <li
          v-for="doc in sortedDocuments"
          :key="doc.id"
          class="px-3 py-2 hover:bg-gray-750 cursor-pointer transition-colors"
          :class="{ 'bg-gray-700': selectedId === doc.id }"
          @click="selectDocument(doc)"
        >
          <div class="flex items-center gap-2 mb-1">
            <TypeBadge :type="doc.doc_type" />
            <span class="text-sm text-gray-200 truncate flex-1">
              {{ doc.title || doc.id }}
            </span>
          </div>
          <div class="flex items-center gap-2 text-xs text-gray-500">
            <span>{{ doc.repository }}</span>
            <span v-if="doc.created_at">{{ formatTime(doc.created_at) }}</span>
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.bg-gray-750 {
  background-color: rgb(42, 48, 60);
}
</style>
