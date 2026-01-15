<script setup lang="ts">
import { ref } from 'vue'
import type { SearchResponse, SearchResult } from '../types'
import { client } from '../api/client'
import { getBestScore } from '../types'
import TypeBadge from './TypeBadge.vue'

const emit = defineEmits<{
  selectResult: [result: SearchResult]
}>()

const query = ref('')
const response = ref<SearchResponse | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

let debounceTimer: ReturnType<typeof setTimeout> | null = null

function onInput() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(search, 300)
}

async function search() {
  const q = query.value.trim()
  if (!q) {
    response.value = null
    return
  }

  loading.value = true
  error.value = null
  try {
    response.value = await client.search(q, { limit: 20, rerank: true })
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Search failed'
    response.value = null
  } finally {
    loading.value = false
  }
}

function selectResult(result: SearchResult) {
  emit('selectResult', result)
}

function formatScore(scores: SearchResult['scores']): string {
  const best = getBestScore(scores)
  return best.toFixed(2)
}
</script>

<template>
  <div class="card">
    <div class="p-3 border-b border-gray-700">
      <div class="flex items-center gap-2">
        <svg
          class="w-5 h-5 text-gray-500"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
          />
        </svg>
        <input
          v-model="query"
          type="text"
          placeholder="Search memory..."
          class="input flex-1"
          @input="onInput"
          @keyup.enter="search"
        />
        <span v-if="response" class="text-xs text-gray-500">
          {{ response.result_count }} results in {{ response.timing_ms.toFixed(0) }}ms
        </span>
      </div>
    </div>

    <div v-if="loading" class="p-3 text-gray-400 text-sm">Searching...</div>

    <div v-else-if="error" class="p-3 text-red-400 text-sm">{{ error }}</div>

    <div
      v-else-if="response && response.results.length > 0"
      class="max-h-48 overflow-auto"
    >
      <ul class="divide-y divide-gray-700">
        <li
          v-for="result in response.results"
          :key="result.id"
          class="px-3 py-2 hover:bg-gray-750 cursor-pointer transition-colors"
          @click="selectResult(result)"
        >
          <div class="flex items-center gap-2">
            <TypeBadge :type="result.metadata.type as string" />
            <span class="text-sm text-gray-200 truncate flex-1">
              {{ result.metadata.title || result.id }}
            </span>
            <span class="text-xs text-gray-500 font-mono">
              {{ formatScore(result.scores) }}
            </span>
          </div>
          <p class="text-xs text-gray-500 mt-1 line-clamp-2">
            {{ result.content_preview }}
          </p>
        </li>
      </ul>
    </div>

    <div
      v-else-if="query.trim() && response && response.results.length === 0"
      class="p-3 text-gray-500 text-sm"
    >
      No results found
    </div>
  </div>
</template>

<style scoped>
.bg-gray-750 {
  background-color: rgb(42, 48, 60);
}
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
