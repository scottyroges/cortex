<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { Stats } from '../types'
import { client } from '../api/client'

const props = defineProps<{
  activeTypeFilter?: string | null
  activeRepoFilter?: string | null
}>()

const emit = defineEmits<{
  'filter-type': [type: string | null]
  'filter-repo': [repo: string | null]
}>()

const stats = ref<Stats | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

async function loadStats() {
  loading.value = true
  error.value = null
  try {
    stats.value = await client.getStats()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to load stats'
  } finally {
    loading.value = false
  }
}

function toggleTypeFilter(type: string) {
  emit('filter-type', props.activeTypeFilter === type ? null : type)
}

function toggleRepoFilter(repo: string) {
  emit('filter-repo', props.activeRepoFilter === repo ? null : repo)
}

function clearFilters() {
  emit('filter-type', null)
  emit('filter-repo', null)
}

onMounted(loadStats)

defineExpose({ refresh: loadStats })
</script>

<template>
  <div class="card p-4 h-full overflow-auto">
    <h2 class="text-lg font-semibold mb-4 text-gray-100">Memory Stats</h2>

    <div v-if="loading" class="text-gray-400">Loading...</div>

    <div v-else-if="error" class="text-red-400 text-sm">{{ error }}</div>

    <div v-else-if="stats" class="space-y-4">
      <div
        class="cursor-pointer group"
        @click="clearFilters"
        :title="activeTypeFilter || activeRepoFilter ? 'Click to clear filters' : ''"
      >
        <div class="text-3xl font-bold text-blue-400 group-hover:text-blue-300 transition-colors">
          {{ stats.total_documents.toLocaleString() }}
        </div>
        <div class="text-sm text-gray-400">Total Documents</div>
      </div>

      <div v-if="Object.keys(stats.by_type).length > 0">
        <h3 class="text-sm font-medium text-gray-300 mb-2">By Type</h3>
        <ul class="space-y-1">
          <li
            v-for="(count, type) in stats.by_type"
            :key="type"
            class="flex justify-between text-sm px-2 py-1 -mx-2 rounded cursor-pointer transition-colors"
            :class="activeTypeFilter === type
              ? 'bg-blue-900/50 text-blue-300'
              : 'hover:bg-gray-700'"
            @click="toggleTypeFilter(String(type))"
          >
            <span class="capitalize" :class="activeTypeFilter === type ? 'text-blue-300' : 'text-gray-400'">{{ type }}</span>
            <span class="font-medium" :class="activeTypeFilter === type ? 'text-blue-200' : 'text-gray-200'">{{ count }}</span>
          </li>
        </ul>
      </div>

      <div v-if="Object.keys(stats.by_repository).length > 0">
        <h3 class="text-sm font-medium text-gray-300 mb-2">By Repository</h3>
        <ul class="space-y-1">
          <li
            v-for="(count, repo) in stats.by_repository"
            :key="repo"
            class="flex justify-between text-sm px-2 py-1 -mx-2 rounded cursor-pointer transition-colors"
            :class="activeRepoFilter === repo
              ? 'bg-blue-900/50 text-blue-300'
              : 'hover:bg-gray-700'"
            @click="toggleRepoFilter(String(repo))"
          >
            <span class="truncate mr-2" :class="activeRepoFilter === repo ? 'text-blue-300' : 'text-gray-400'">{{ repo }}</span>
            <span class="font-medium" :class="activeRepoFilter === repo ? 'text-blue-200' : 'text-gray-200'">{{ count }}</span>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>
