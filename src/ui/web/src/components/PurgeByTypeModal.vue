<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { PurgeResult } from '../types'
import { client } from '../api/client'
import { useBrowserStore, useUIStore } from '../stores'

const browserStore = useBrowserStore()
const uiStore = useUIStore()

const show = computed(() => uiStore.activeModal === 'purge')

// Form state
const selectedRepo = ref<string>('')
const selectedType = ref<string>('')
const beforeDate = ref<string>('')
const afterDate = ref<string>('')

// Operation state
const loading = ref(false)
const previewResult = ref<PurgeResult | null>(null)
const error = ref<string | null>(null)
const confirmMode = ref(false)

const hasFilters = computed(() =>
  selectedRepo.value || selectedType.value || beforeDate.value || afterDate.value
)

// Reset state when modal opens/closes
watch(show, (visible) => {
  if (!visible) {
    resetState()
  }
})

function resetState() {
  selectedRepo.value = ''
  selectedType.value = ''
  beforeDate.value = ''
  afterDate.value = ''
  previewResult.value = null
  error.value = null
  confirmMode.value = false
}

async function preview() {
  if (!hasFilters.value) return
  loading.value = true
  error.value = null
  previewResult.value = null

  try {
    previewResult.value = await client.purge({
      repository: selectedRepo.value || undefined,
      doc_type: selectedType.value || undefined,
      before_date: beforeDate.value || undefined,
      after_date: afterDate.value || undefined,
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
    await client.purge({
      repository: selectedRepo.value || undefined,
      doc_type: selectedType.value || undefined,
      before_date: beforeDate.value || undefined,
      after_date: afterDate.value || undefined,
      dry_run: false,
    })
    browserStore.refresh()
    closeModal()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Purge failed'
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
          <h2 class="text-lg font-semibold text-gray-100">Purge Documents</h2>
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
            Delete documents matching the specified filters. At least one filter is required.
          </p>

          <!-- Repository -->
          <div>
            <label class="block text-sm text-gray-300 mb-1">Repository</label>
            <select
              v-model="selectedRepo"
              class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-gray-200 focus:border-blue-500 focus:outline-none"
            >
              <option value="">All repositories</option>
              <option v-for="repo in browserStore.repositories" :key="repo" :value="repo">
                {{ repo }}
              </option>
            </select>
          </div>

          <!-- Document Type -->
          <div>
            <label class="block text-sm text-gray-300 mb-1">Document Type</label>
            <select
              v-model="selectedType"
              class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-gray-200 focus:border-blue-500 focus:outline-none"
            >
              <option value="">All types</option>
              <option v-for="type in browserStore.documentTypes" :key="type" :value="type">
                {{ type }}
              </option>
            </select>
          </div>

          <!-- Date Range -->
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm text-gray-300 mb-1">Created Before</label>
              <input
                v-model="beforeDate"
                type="date"
                class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-gray-200 focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-300 mb-1">Created After</label>
              <input
                v-model="afterDate"
                type="date"
                class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-gray-200 focus:border-blue-500 focus:outline-none"
              />
            </div>
          </div>

          <!-- Preview Results -->
          <div v-if="previewResult" class="p-3 bg-gray-900 rounded border border-gray-700">
            <h3 class="text-sm font-medium text-gray-300 mb-2">Preview Results</h3>
            <p class="text-lg font-bold" :class="previewResult.matched_count > 0 ? 'text-amber-400' : 'text-gray-400'">
              {{ previewResult.matched_count }} documents would be deleted
            </p>
            <div v-if="previewResult.sample_ids.length > 0" class="mt-2">
              <p class="text-xs text-gray-500 mb-1">Sample IDs:</p>
              <ul class="text-xs text-gray-400 font-mono">
                <li v-for="id in previewResult.sample_ids.slice(0, 5)" :key="id" class="truncate">
                  {{ id }}
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
              <strong>{{ previewResult.matched_count }}</strong>
              documents. This cannot be undone.
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
            :disabled="!hasFilters || loading"
            @click="preview"
          >
            {{ loading ? 'Loading...' : 'Preview' }}
          </button>
          <button
            v-if="previewResult && previewResult.matched_count > 0 && !confirmMode"
            class="px-4 py-2 text-sm bg-amber-600 hover:bg-amber-500 text-white rounded transition-colors"
            @click="confirmMode = true"
          >
            Delete...
          </button>
          <button
            v-if="confirmMode"
            class="px-4 py-2 text-sm bg-red-600 hover:bg-red-500 text-white rounded transition-colors"
            :disabled="loading"
            @click="execute"
          >
            {{ loading ? 'Deleting...' : 'Yes, Delete' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
