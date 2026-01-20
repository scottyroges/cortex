<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { Stats, PurgeResult, CleanupResult } from '../types'
import { client } from '../api/client'

const props = defineProps<{
  show: boolean
  stats: Stats | null
}>()

const emit = defineEmits<{
  close: []
  purged: []
}>()

// Tab state
const activeTab = ref<'purge' | 'cleanup'>('purge')

// Purge form state
const selectedRepo = ref<string>('')
const selectedType = ref<string>('')
const beforeDate = ref<string>('')
const afterDate = ref<string>('')

// Cleanup form state
const cleanupRepo = ref<string>('')
const cleanupPath = ref<string>('')

// Operation state
const loading = ref(false)
const previewResult = ref<PurgeResult | CleanupResult | null>(null)
const error = ref<string | null>(null)
const confirmMode = ref(false)

const repositories = computed(() => props.stats ? Object.keys(props.stats.by_repository) : [])
const documentTypes = computed(() => props.stats ? Object.keys(props.stats.by_type) : [])

const hasPurgeFilters = computed(() =>
  selectedRepo.value || selectedType.value || beforeDate.value || afterDate.value
)

const hasCleanupParams = computed(() =>
  cleanupRepo.value && cleanupPath.value
)

// Reset state when modal opens/closes
watch(() => props.show, (show) => {
  if (!show) {
    resetState()
  }
})

function resetState() {
  selectedRepo.value = ''
  selectedType.value = ''
  beforeDate.value = ''
  afterDate.value = ''
  cleanupRepo.value = ''
  cleanupPath.value = ''
  previewResult.value = null
  error.value = null
  confirmMode.value = false
}

async function previewPurge() {
  if (!hasPurgeFilters.value) return
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

async function executePurge() {
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
    emit('purged')
    closeModal()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Purge failed'
  } finally {
    loading.value = false
    confirmMode.value = false
  }
}

async function previewCleanup() {
  if (!hasCleanupParams.value) return
  loading.value = true
  error.value = null
  previewResult.value = null

  try {
    previewResult.value = await client.cleanup({
      repository: cleanupRepo.value,
      path: cleanupPath.value,
      dry_run: true,
    })
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Preview failed'
  } finally {
    loading.value = false
  }
}

async function executeCleanup() {
  loading.value = true
  error.value = null

  try {
    await client.cleanup({
      repository: cleanupRepo.value,
      path: cleanupPath.value,
      dry_run: false,
    })
    emit('purged')
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
  emit('close')
}

function isPurgeResult(result: PurgeResult | CleanupResult): result is PurgeResult {
  return 'matched_count' in result
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
          <h2 class="text-lg font-semibold text-gray-100">Manage Storage</h2>
          <button
            class="text-gray-400 hover:text-gray-200 text-xl leading-none"
            @click="closeModal"
          >
            &times;
          </button>
        </div>

        <!-- Tabs -->
        <div class="flex border-b border-gray-700">
          <button
            class="flex-1 px-4 py-2 text-sm font-medium transition-colors"
            :class="activeTab === 'purge'
              ? 'text-blue-400 border-b-2 border-blue-400 bg-gray-700/50'
              : 'text-gray-400 hover:text-gray-200'"
            @click="activeTab = 'purge'; previewResult = null; error = null"
          >
            Purge by Filters
          </button>
          <button
            class="flex-1 px-4 py-2 text-sm font-medium transition-colors"
            :class="activeTab === 'cleanup'
              ? 'text-blue-400 border-b-2 border-blue-400 bg-gray-700/50'
              : 'text-gray-400 hover:text-gray-200'"
            @click="activeTab = 'cleanup'; previewResult = null; error = null"
          >
            Cleanup Orphaned
          </button>
        </div>

        <!-- Content -->
        <div class="p-4 overflow-auto flex-1">
          <!-- Purge Tab -->
          <div v-if="activeTab === 'purge'" class="space-y-4">
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
                <option v-for="repo in repositories" :key="repo" :value="repo">
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
                <option v-for="type in documentTypes" :key="type" :value="type">
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
          </div>

          <!-- Cleanup Tab -->
          <div v-if="activeTab === 'cleanup'" class="space-y-4">
            <p class="text-sm text-gray-400">
              Remove orphaned documents for files that no longer exist on disk (file_metadata, insights, dependencies).
            </p>

            <!-- Repository -->
            <div>
              <label class="block text-sm text-gray-300 mb-1">Repository *</label>
              <select
                v-model="cleanupRepo"
                class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-gray-200 focus:border-blue-500 focus:outline-none"
              >
                <option value="">Select repository</option>
                <option v-for="repo in repositories" :key="repo" :value="repo">
                  {{ repo }}
                </option>
              </select>
            </div>

            <!-- Path -->
            <div>
              <label class="block text-sm text-gray-300 mb-1">Repository Path *</label>
              <input
                v-model="cleanupPath"
                type="text"
                class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-gray-200 focus:border-blue-500 focus:outline-none font-mono text-sm"
                placeholder="/absolute/path/to/repo"
              />
              <p class="text-xs text-gray-500 mt-1">Absolute path to repository root for file existence checks</p>
            </div>
          </div>

          <!-- Preview Results -->
          <div v-if="previewResult" class="mt-4 p-3 bg-gray-900 rounded border border-gray-700">
            <h3 class="text-sm font-medium text-gray-300 mb-2">Preview Results</h3>

            <!-- Purge Result -->
            <div v-if="isPurgeResult(previewResult)">
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

            <!-- Cleanup Result -->
            <div v-else>
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
          </div>

          <!-- Error -->
          <p v-if="error" class="mt-4 text-red-400 text-sm">{{ error }}</p>

          <!-- Confirm Banner -->
          <div v-if="confirmMode && previewResult" class="mt-4 p-3 bg-red-900/50 border border-red-700 rounded">
            <p class="text-red-200 text-sm">
              This will permanently delete
              <strong>{{ isPurgeResult(previewResult) ? previewResult.matched_count : previewResult.total_orphaned }}</strong>
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

          <!-- Purge buttons -->
          <template v-if="activeTab === 'purge'">
            <button
              v-if="!confirmMode"
              class="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="!hasPurgeFilters || loading"
              @click="previewPurge"
            >
              {{ loading ? 'Loading...' : 'Preview' }}
            </button>
            <button
              v-if="previewResult && isPurgeResult(previewResult) && previewResult.matched_count > 0 && !confirmMode"
              class="px-4 py-2 text-sm bg-amber-600 hover:bg-amber-500 text-white rounded transition-colors"
              @click="confirmMode = true"
            >
              Delete...
            </button>
            <button
              v-if="confirmMode"
              class="px-4 py-2 text-sm bg-red-600 hover:bg-red-500 text-white rounded transition-colors"
              :disabled="loading"
              @click="executePurge"
            >
              {{ loading ? 'Deleting...' : 'Yes, Delete' }}
            </button>
          </template>

          <!-- Cleanup buttons -->
          <template v-if="activeTab === 'cleanup'">
            <button
              v-if="!confirmMode"
              class="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="!hasCleanupParams || loading"
              @click="previewCleanup"
            >
              {{ loading ? 'Loading...' : 'Preview' }}
            </button>
            <button
              v-if="previewResult && !isPurgeResult(previewResult) && previewResult.total_orphaned > 0 && !confirmMode"
              class="px-4 py-2 text-sm bg-amber-600 hover:bg-amber-500 text-white rounded transition-colors"
              @click="confirmMode = true"
            >
              Cleanup...
            </button>
            <button
              v-if="confirmMode"
              class="px-4 py-2 text-sm bg-red-600 hover:bg-red-500 text-white rounded transition-colors"
              :disabled="loading"
              @click="executeCleanup"
            >
              {{ loading ? 'Cleaning...' : 'Yes, Cleanup' }}
            </button>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>
