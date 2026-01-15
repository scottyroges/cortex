<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import type { DocumentSummary, Stats } from '../types'
import { client } from '../api/client'
import TypeBadge from './TypeBadge.vue'

const props = defineProps<{
  stats: Stats | null
}>()

const emit = defineEmits<{
  select: [doc: DocumentSummary]
}>()

const documents = ref<DocumentSummary[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const selectedId = ref<string | null>(null)

const typeFilter = ref('')
const repoFilter = ref('')

const typeOptions = computed(() => {
  if (!props.stats) return []
  return Object.keys(props.stats.by_type)
})

const repoOptions = computed(() => {
  if (!props.stats) return []
  return Object.keys(props.stats.by_repository)
})

async function loadDocuments() {
  loading.value = true
  error.value = null
  try {
    documents.value = await client.listDocuments({
      doc_type: typeFilter.value || undefined,
      repository: repoFilter.value || undefined,
      limit: 100,
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

watch([typeFilter, repoFilter], loadDocuments)
onMounted(loadDocuments)

defineExpose({ refresh: loadDocuments })
</script>

<template>
  <div class="card h-full flex flex-col">
    <div class="p-3 border-b border-gray-700 flex gap-2">
      <select v-model="typeFilter" class="select flex-1 text-sm">
        <option value="">All Types</option>
        <option v-for="type in typeOptions" :key="type" :value="type">
          {{ type }}
        </option>
      </select>
      <select v-model="repoFilter" class="select flex-1 text-sm">
        <option value="">All Repos</option>
        <option v-for="repo in repoOptions" :key="repo" :value="repo">
          {{ repo }}
        </option>
      </select>
    </div>

    <div class="flex-1 overflow-auto">
      <div v-if="loading" class="p-4 text-gray-400">Loading...</div>

      <div v-else-if="error" class="p-4 text-red-400 text-sm">{{ error }}</div>

      <div v-else-if="documents.length === 0" class="p-4 text-gray-500 text-sm">
        No documents found
      </div>

      <ul v-else class="divide-y divide-gray-700">
        <li
          v-for="doc in documents"
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
