<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { CleanupResult } from '../types'
import { client } from '../api/client'
import { useBrowserStore, useUIStore } from '../stores'

const browserStore = useBrowserStore()
const uiStore = useUIStore()

const show = computed(() => uiStore.activeModal === 'cleanup')

// Form state
const selectedRepo = ref<string>('')
const repoPath = ref<string>('')

// Operation state
const loading = ref(false)
const previewResult = ref<CleanupResult | null>(null)
const error = ref<string | null>(null)
const confirmMode = ref(false)

const hasParams = computed(() => selectedRepo.value && repoPath.value)

// Reset state when modal opens/closes
watch(show, (visible) => {
  if (!visible) {
    resetState()
  }
})

function resetState() {
  selectedRepo.value = ''
  repoPath.value = ''
  previewResult.value = null
  error.value = null
  confirmMode.value = false
}

async function preview() {
  if (!hasParams.value) return
  loading.value = true
  error.value = null
  previewResult.value = null

  try {
    previewResult.value = await client.cleanup({
      repository: selectedRepo.value,
      path: repoPath.value,
      dry_run: true,
    })
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Preview failed'
  } finally {
    loading.value = false
  }
}

async function execute() {
  loading.value = true
  error.value = null

  try {
    await client.cleanup({
      repository: selectedRepo.value,
      path: repoPath.value,
      dry_run: false,
    })
    browserStore.refresh()
    closeModal()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Cleanup failed'
  } finally {
    loading.value = false
    confirmMode.value = false
  }
}

function closeModal() {
  resetState()
  uiStore.closeModal()
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="show"
      class="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      @click.self="closeModal"
    >
      <div class="bg-gray-800 rounded-lg shadow-xl w-full max-w-lg mx-4 max-h-[90vh] flex flex-col">
        <!-- Header -->
        <div class="p-4 border-b border-gray-700 flex justify-between items-center">
          <h2 class="text-lg font-semibold text-gray-100">Cleanup Orphaned Documents</h2>
          <button
            class="text-gray-400 hover:text-gray-200 text-xl leading-none"
            @click="closeModal"
          >
            &times;
          </button>
        </div>

        <!-- Content -->
        <div class="p-4 overflow-auto flex-1 space-y-4">
          <p class="text-sm text-gray-400">
            Remove orphaned documents for files that no longer exist on disk (file_metadata, insights, dependencies).
          </p>

          <!-- Repository -->
          <div>
            <label class="block text-sm text-gray-300 mb-1">Repository *</label>
            <select
              v-model="selectedRepo"
              class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-gray-200 focus:border-blue-500 focus:outline-none"
            >
              <option value="">Select repository</option>
              <option v-for="repo in browserStore.repositories" :key="repo" :value="repo">
                {{ repo }}
              </option>
            </select>
          </div>

          <!-- Path -->
          <div>
            <label class="block text-sm text-gray-300 mb-1">Repository Path *</label>
            <input
              v-model="repoPath"
              type="text"
              class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-gray-200 focus:border-blue-500 focus:outline-none font-mono text-sm"
              placeholder="/absolute/path/to/repo"
            />
            <p class="text-xs text-gray-500 mt-1">Absolute path to repository root for file existence checks</p>
          </div>

          <!-- Preview Results -->
          <div v-if="previewResult" class="p-3 bg-gray-900 rounded border border-gray-700">
            <h3 class="text-sm font-medium text-gray-300 mb-2">Preview Results</h3>
            <p class="text-lg font-bold" :class="previewResult.total_orphaned > 0 ? 'text-amber-400' : 'text-gray-400'">
              {{ previewResult.total_orphaned }} orphaned documents found
            </p>
            <ul class="mt-2 text-sm text-gray-400 space-y-1">
              <li>File metadata: {{ previewResult.orphaned_file_metadata.count }}</li>
              <li>Insights: {{ previewResult.orphaned_insights.count }}</li>
              <li>Dependencies: {{ previewResult.orphaned_dependencies.count }}</li>
            </ul>
            <div v-if="previewResult.orphaned_file_metadata.orphaned_files?.length" class="mt-2">
              <p class="text-xs text-gray-500 mb-1">Sample orphaned files:</p>
              <ul class="text-xs text-gray-400 font-mono">
                <li v-for="f in previewResult.orphaned_file_metadata.orphaned_files.slice(0, 3)" :key="f" class="truncate">
                  {{ f }}
                </li>
              </ul>
            </div>
          </div>

          <!-- Error -->
          <p v-if="error" class="text-red-400 text-sm">{{ error }}</p>

          <!-- Confirm Banner -->
          <div v-if="confirmMode && previewResult" class="p-3 bg-red-900/50 border border-red-700 rounded">
            <p class="text-red-200 text-sm">
              This will permanently delete
              <strong>{{ previewResult.total_orphaned }}</strong>
              orphaned documents. This cannot be undone.
            </p>
          </div>
        </div>

        <!-- Footer -->
        <div class="p-4 border-t border-gray-700 flex justify-end gap-2">
          <button
            class="px-4 py-2 text-sm bg-gray-600 hover:bg-gray-500 text-white rounded transition-colors"
            @click="closeModal"
          >
            Cancel
          </button>

          <button
            v-if="!confirmMode"
            class="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            :disabled="!hasParams || loading"
            @click="preview"
          >
            {{ loading ? 'Loading...' : 'Preview' }}
          </button>
          <button
            v-if="previewResult && previewResult.total_orphaned > 0 && !confirmMode"
            class="px-4 py-2 text-sm bg-amber-600 hover:bg-amber-500 text-white rounded transition-colors"
            @click="confirmMode = true"
          >
            Cleanup...
          </button>
          <button
            v-if="confirmMode"
            class="px-4 py-2 text-sm bg-red-600 hover:bg-red-500 text-white rounded transition-colors"
            :disabled="loading"
            @click="execute"
          >
            {{ loading ? 'Cleaning...' : 'Yes, Cleanup' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
