<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import type { Document, DocumentSummary } from '../types'
import { client } from '../api/client'
import TypeBadge from './TypeBadge.vue'

const props = defineProps<{
  summary: DocumentSummary | null
}>()

const emit = defineEmits<{
  documentDeleted: [id: string]
  documentUpdated: [id: string]
}>()

const document = ref<Document | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

// Edit/Delete state
const editing = ref(false)
const confirmingDelete = ref(false)
const saving = ref(false)
const deleteError = ref<string | null>(null)
const saveError = ref<string | null>(null)

// Edit form state
const editTitle = ref('')
const editContent = ref('')
const editTags = ref<string[]>([])
const editFiles = ref<string[]>([])
const newTag = ref('')
const newFile = ref('')

// Editable fields per document type
const EDITABLE_FIELDS: Record<string, Set<string>> = {
  note: new Set(['title', 'content', 'tags']),
  insight: new Set(['title', 'content', 'tags', 'files']),
  commit: new Set(['content', 'files']),
}

const docType = computed(() => (document.value?.metadata?.type as string) || 'unknown')
const isEditable = computed(() => docType.value in EDITABLE_FIELDS)
const editableFields = computed(() => EDITABLE_FIELDS[docType.value] || new Set())

// Get timestamp with fallback for legacy documents
const documentTimestamp = computed(() => {
  if (!document.value?.metadata) return undefined
  const meta = document.value.metadata
  return (meta.created_at || meta.updated_at) as string | undefined
})

async function loadDocument(id: string) {
  loading.value = true
  error.value = null
  try {
    document.value = await client.getDocument(id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to load document'
    document.value = null
  } finally {
    loading.value = false
  }
}

watch(
  () => props.summary?.id,
  (id) => {
    if (id) {
      loadDocument(id)
    } else {
      document.value = null
    }
  },
  { immediate: true }
)

function formatContent(content: string): string {
  return content
    .replace(/\\n/g, '\n')
    .replace(/\\t/g, '    ')
    .replace(/\\r/g, '\r')
    .replace(/\\\\/g, '\\')
}

function formatTimestamp(dateStr?: string): string {
  if (!dateStr) return ''
  try {
    return new Date(dateStr).toLocaleString()
  } catch {
    return dateStr
  }
}

function parseJson(value: unknown): string[] {
  if (!value) return []
  if (Array.isArray(value)) return value
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      if (Array.isArray(parsed)) return parsed
    } catch {
      return value.split(',').map((s) => s.trim())
    }
  }
  return []
}

function startEditing() {
  if (!document.value) return
  editTitle.value = (document.value.metadata.title as string) || ''
  editContent.value = formatContent(document.value.content)
  editTags.value = [...parseJson(document.value.metadata.tags)]
  editFiles.value = [...parseJson(document.value.metadata.files)]
  saveError.value = null
  editing.value = true
}

function cancelEditing() {
  editing.value = false
  saveError.value = null
}

async function saveChanges() {
  if (!document.value) return

  saving.value = true
  saveError.value = null

  try {
    const data: Record<string, unknown> = {}
    if (editableFields.value.has('title')) data.title = editTitle.value
    if (editableFields.value.has('content')) data.content = editContent.value
    if (editableFields.value.has('tags')) data.tags = editTags.value
    if (editableFields.value.has('files')) data.files = editFiles.value

    await client.updateDocument(document.value.id, data)
    editing.value = false
    emit('documentUpdated', document.value.id)
    // Reload the document to show updated data
    await loadDocument(document.value.id)
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : 'Failed to save changes'
  } finally {
    saving.value = false
  }
}

function confirmDelete() {
  confirmingDelete.value = true
  deleteError.value = null
}

function cancelDelete() {
  confirmingDelete.value = false
  deleteError.value = null
}

async function executeDelete() {
  if (!document.value) return

  saving.value = true
  deleteError.value = null

  try {
    await client.deleteDocument(document.value.id)
    const deletedId = document.value.id
    document.value = null
    confirmingDelete.value = false
    emit('documentDeleted', deletedId)
  } catch (e) {
    deleteError.value = e instanceof Error ? e.message : 'Failed to delete document'
  } finally {
    saving.value = false
  }
}

function addTag() {
  const tag = newTag.value.trim()
  if (tag && !editTags.value.includes(tag)) {
    editTags.value.push(tag)
    newTag.value = ''
  }
}

function removeTag(tag: string) {
  editTags.value = editTags.value.filter((t) => t !== tag)
}

function addFile() {
  const file = newFile.value.trim()
  if (file && !editFiles.value.includes(file)) {
    editFiles.value.push(file)
    newFile.value = ''
  }
}

function removeFile(file: string) {
  editFiles.value = editFiles.value.filter((f) => f !== file)
}
</script>

<template>
  <div class="card h-full flex flex-col overflow-hidden">
    <div v-if="!summary" class="p-4 text-gray-500 text-center flex-1 flex items-center justify-center">
      Select a document to view details
    </div>

    <div v-else-if="loading" class="p-4 text-gray-400">Loading...</div>

    <div v-else-if="error" class="p-4 text-red-400 text-sm">{{ error }}</div>

    <template v-else-if="document">
      <!-- Delete Confirmation Banner -->
      <div v-if="confirmingDelete" class="bg-red-900/50 border-b border-red-700 p-3 flex-shrink-0">
        <div class="flex items-center justify-between">
          <span class="text-red-200">Delete this document permanently?</span>
          <div class="flex gap-2">
            <button
              class="px-3 py-1 text-sm bg-red-600 hover:bg-red-500 text-white rounded transition-colors"
              :disabled="saving"
              @click="executeDelete"
            >
              {{ saving ? 'Deleting...' : 'Yes, Delete' }}
            </button>
            <button
              class="px-3 py-1 text-sm bg-gray-600 hover:bg-gray-500 text-white rounded transition-colors"
              :disabled="saving"
              @click="cancelDelete"
            >
              Cancel
            </button>
          </div>
        </div>
        <p v-if="deleteError" class="text-red-400 text-sm mt-2">{{ deleteError }}</p>
      </div>

      <div class="p-4 border-b border-gray-700 flex-shrink-0">
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center gap-2">
            <TypeBadge :type="document.metadata.type as string" />
            <span class="text-xs text-gray-500">{{ document.id }}</span>
          </div>
          <!-- Action buttons -->
          <div v-if="!editing && !confirmingDelete" class="flex gap-2">
            <button
              v-if="isEditable"
              class="px-2 py-1 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded transition-colors"
              @click="startEditing"
            >
              Edit
            </button>
            <button
              class="px-2 py-1 text-xs bg-red-600/80 hover:bg-red-500 text-white rounded transition-colors"
              @click="confirmDelete"
            >
              Delete
            </button>
          </div>
        </div>
        <h2 class="text-lg font-semibold text-gray-100">
          {{ document.metadata.title || 'Untitled' }}
        </h2>

        <div class="mt-3 grid grid-cols-2 gap-2 text-sm">
          <div v-if="document.metadata.repository">
            <span class="text-gray-500">Repository:</span>
            <span class="ml-2 text-gray-300">{{ document.metadata.repository }}</span>
          </div>
          <div v-if="documentTimestamp">
            <span class="text-gray-500">Created:</span>
            <span class="ml-2 text-gray-300">
              {{ formatTimestamp(documentTimestamp) }}
            </span>
          </div>
          <div v-if="document.metadata.updated_at && document.metadata.updated_at !== document.metadata.created_at">
            <span class="text-gray-500">Updated:</span>
            <span class="ml-2 text-gray-300">
              {{ formatTimestamp(document.metadata.updated_at as string) }}
            </span>
          </div>
          <div v-if="document.metadata.status">
            <span class="text-gray-500">Status:</span>
            <span class="ml-2 text-gray-300">{{ document.metadata.status }}</span>
          </div>
          <div v-if="document.metadata.initiative_name">
            <span class="text-gray-500">Initiative:</span>
            <span class="ml-2 text-gray-300">{{ document.metadata.initiative_name }}</span>
          </div>
        </div>

        <div v-if="document.metadata.tags" class="mt-2">
          <span class="text-gray-500 text-sm">Tags:</span>
          <span
            v-for="tag in parseJson(document.metadata.tags)"
            :key="tag"
            class="ml-2 inline-block bg-gray-700 text-gray-300 text-xs px-2 py-0.5 rounded"
          >
            {{ tag }}
          </span>
        </div>

        <div v-if="document.metadata.files" class="mt-2">
          <span class="text-gray-500 text-sm">Files:</span>
          <ul class="mt-1 text-xs text-gray-400 font-mono">
            <li v-for="file in parseJson(document.metadata.files).slice(0, 5)" :key="file">
              {{ file }}
            </li>
            <li v-if="parseJson(document.metadata.files).length > 5" class="text-gray-500">
              ... and {{ parseJson(document.metadata.files).length - 5 }} more
            </li>
          </ul>
        </div>

        <div
          v-if="document.metadata.last_validation_result"
          class="mt-2 text-sm"
          :class="{
            'text-green-400': document.metadata.last_validation_result === 'still_valid',
            'text-yellow-400': document.metadata.last_validation_result === 'partially_valid',
            'text-red-400': document.metadata.last_validation_result === 'no_longer_valid',
          }"
        >
          Validation: {{ document.metadata.last_validation_result }}
        </div>
      </div>

      <!-- Edit Mode -->
      <div v-if="editing" class="flex-1 overflow-auto p-4 flex flex-col gap-4">
        <!-- Title (if editable) -->
        <div v-if="editableFields.has('title')">
          <label class="block text-sm text-gray-400 mb-1">Title</label>
          <input
            v-model="editTitle"
            type="text"
            class="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-gray-200 focus:border-blue-500 focus:outline-none"
            placeholder="Document title"
          />
        </div>

        <!-- Tags (if editable) -->
        <div v-if="editableFields.has('tags')">
          <label class="block text-sm text-gray-400 mb-1">Tags</label>
          <div class="flex flex-wrap gap-2 mb-2">
            <span
              v-for="tag in editTags"
              :key="tag"
              class="inline-flex items-center bg-gray-700 text-gray-300 text-xs px-2 py-1 rounded"
            >
              {{ tag }}
              <button
                class="ml-1 text-gray-500 hover:text-red-400"
                @click="removeTag(tag)"
              >
                &times;
              </button>
            </span>
          </div>
          <div class="flex gap-2">
            <input
              v-model="newTag"
              type="text"
              class="flex-1 bg-gray-800 border border-gray-600 rounded px-3 py-1 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
              placeholder="Add tag..."
              @keyup.enter="addTag"
            />
            <button
              class="px-3 py-1 text-sm bg-gray-600 hover:bg-gray-500 text-white rounded transition-colors"
              @click="addTag"
            >
              Add
            </button>
          </div>
        </div>

        <!-- Files (if editable) -->
        <div v-if="editableFields.has('files')">
          <label class="block text-sm text-gray-400 mb-1">Linked Files</label>
          <ul class="text-xs text-gray-400 font-mono mb-2">
            <li v-for="file in editFiles" :key="file" class="flex items-center gap-2 py-0.5">
              <span class="flex-1">{{ file }}</span>
              <button
                class="text-gray-500 hover:text-red-400"
                @click="removeFile(file)"
              >
                &times;
              </button>
            </li>
          </ul>
          <div class="flex gap-2">
            <input
              v-model="newFile"
              type="text"
              class="flex-1 bg-gray-800 border border-gray-600 rounded px-3 py-1 text-sm text-gray-200 focus:border-blue-500 focus:outline-none font-mono"
              placeholder="Add file path..."
              @keyup.enter="addFile"
            />
            <button
              class="px-3 py-1 text-sm bg-gray-600 hover:bg-gray-500 text-white rounded transition-colors"
              @click="addFile"
            >
              Add
            </button>
          </div>
        </div>

        <!-- Content -->
        <div v-if="editableFields.has('content')" class="flex-1 flex flex-col">
          <label class="block text-sm text-gray-400 mb-1">Content</label>
          <textarea
            v-model="editContent"
            class="flex-1 min-h-48 bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm text-gray-200 font-mono focus:border-blue-500 focus:outline-none resize-none"
            placeholder="Document content..."
          ></textarea>
        </div>

        <!-- Save/Cancel buttons -->
        <div class="flex gap-2 pt-2 border-t border-gray-700">
          <button
            class="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded transition-colors"
            :disabled="saving"
            @click="saveChanges"
          >
            {{ saving ? 'Saving...' : 'Save Changes' }}
          </button>
          <button
            class="px-4 py-2 text-sm bg-gray-600 hover:bg-gray-500 text-white rounded transition-colors"
            :disabled="saving"
            @click="cancelEditing"
          >
            Cancel
          </button>
        </div>
        <p v-if="saveError" class="text-red-400 text-sm">{{ saveError }}</p>
      </div>

      <!-- View Mode -->
      <div v-else class="flex-1 overflow-auto p-4">
        <pre class="text-sm text-gray-300 whitespace-pre-wrap font-mono leading-relaxed">{{ formatContent(document.content) }}</pre>
      </div>
    </template>
  </div>
</template>
