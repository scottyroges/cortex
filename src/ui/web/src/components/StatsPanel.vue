<script setup lang="ts">
import { onMounted } from 'vue'
import { useBrowserStore, useUIStore } from '../stores'

const browserStore = useBrowserStore()
const uiStore = useUIStore()

function toggleTypeFilter(type: string) {
  browserStore.setTypeFilter(browserStore.typeFilter === type ? null : type)
}

function toggleRepoFilter(repo: string) {
  browserStore.setRepoFilter(browserStore.repoFilter === repo ? null : repo)
}

onMounted(() => {
  if (!browserStore.stats) {
    browserStore.loadStats()
  }
})
</script>

<template>
  <div class="card p-4 h-full overflow-auto">
    <h2 class="text-lg font-semibold mb-4 text-gray-100">Memory Stats</h2>

    <div v-if="browserStore.loading" class="text-gray-400">Loading...</div>

    <div v-else-if="browserStore.stats" class="space-y-4">
      <div
        class="cursor-pointer group"
        @click="browserStore.clearFilters"
        :title="browserStore.hasActiveFilters ? 'Click to clear filters' : ''"
      >
        <div class="text-3xl font-bold text-blue-400 group-hover:text-blue-300 transition-colors">
          {{ browserStore.stats.total_documents.toLocaleString() }}
        </div>
        <div class="text-sm text-gray-400">Total Documents</div>
      </div>

      <div v-if="Object.keys(browserStore.stats.by_type).length > 0">
        <h3 class="text-sm font-medium text-gray-300 mb-2">By Type</h3>
        <ul class="space-y-1">
          <li
            v-for="(count, type) in browserStore.stats.by_type"
            :key="type"
            class="flex justify-between text-sm px-2 py-1 -mx-2 rounded cursor-pointer transition-colors"
            :class="browserStore.typeFilter === type
              ? 'bg-blue-900/50 text-blue-300'
              : 'hover:bg-gray-700'"
            @click="toggleTypeFilter(String(type))"
          >
            <span class="capitalize" :class="browserStore.typeFilter === type ? 'text-blue-300' : 'text-gray-400'">{{ type }}</span>
            <span class="font-medium" :class="browserStore.typeFilter === type ? 'text-blue-200' : 'text-gray-200'">{{ count }}</span>
          </li>
        </ul>
      </div>

      <div v-if="Object.keys(browserStore.stats.by_repository).length > 0">
        <h3 class="text-sm font-medium text-gray-300 mb-2">By Repository</h3>
        <ul class="space-y-1">
          <li
            v-for="(count, repo) in browserStore.stats.by_repository"
            :key="repo"
            class="flex justify-between text-sm px-2 py-1 -mx-2 rounded cursor-pointer transition-colors"
            :class="browserStore.repoFilter === repo
              ? 'bg-blue-900/50 text-blue-300'
              : 'hover:bg-gray-700'"
            @click="toggleRepoFilter(String(repo))"
          >
            <span class="truncate mr-2" :class="browserStore.repoFilter === repo ? 'text-blue-300' : 'text-gray-400'">{{ repo }}</span>
            <span class="font-medium" :class="browserStore.repoFilter === repo ? 'text-blue-200' : 'text-gray-200'">{{ count }}</span>
          </li>
        </ul>
      </div>

      <!-- Manage Storage Buttons -->
      <div class="mt-4 pt-4 border-t border-gray-700 space-y-2">
        <button
          class="w-full px-3 py-2 text-sm bg-gray-700 hover:bg-gray-600 text-gray-300 rounded transition-colors"
          @click="uiStore.openPurgeModal"
        >
          Purge Documents...
        </button>
        <button
          class="w-full px-3 py-2 text-sm bg-gray-700 hover:bg-gray-600 text-gray-300 rounded transition-colors"
          @click="uiStore.openCleanupModal"
        >
          Cleanup Orphans...
        </button>
      </div>
    </div>
  </div>
</template>
