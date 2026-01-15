<script setup lang="ts">
import { ref, watch } from 'vue'
import type { Document, DocumentSummary } from '../types'
import { client } from '../api/client'
import TypeBadge from './TypeBadge.vue'

const props = defineProps<{
  summary: DocumentSummary | null
}>()

const document = ref<Document | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

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
</script>

<template>
  <div class="card h-full flex flex-col overflow-hidden">
    <div v-if="!summary" class="p-4 text-gray-500 text-center flex-1 flex items-center justify-center">
      Select a document to view details
    </div>

    <div v-else-if="loading" class="p-4 text-gray-400">Loading...</div>

    <div v-else-if="error" class="p-4 text-red-400 text-sm">{{ error }}</div>

    <template v-else-if="document">
      <div class="p-4 border-b border-gray-700 flex-shrink-0">
        <div class="flex items-center gap-2 mb-2">
          <TypeBadge :type="document.metadata.type as string" />
          <span class="text-xs text-gray-500">{{ document.id }}</span>
        </div>
        <h2 class="text-lg font-semibold text-gray-100">
          {{ document.metadata.title || 'Untitled' }}
        </h2>

        <div class="mt-3 grid grid-cols-2 gap-2 text-sm">
          <div v-if="document.metadata.repository">
            <span class="text-gray-500">Repository:</span>
            <span class="ml-2 text-gray-300">{{ document.metadata.repository }}</span>
          </div>
          <div v-if="document.metadata.created_at">
            <span class="text-gray-500">Created:</span>
            <span class="ml-2 text-gray-300">
              {{ formatTimestamp(document.metadata.created_at as string) }}
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

      <div class="flex-1 overflow-auto p-4">
        <pre class="text-sm text-gray-300 whitespace-pre-wrap font-mono leading-relaxed">{{ formatContent(document.content) }}</pre>
      </div>
    </template>
  </div>
</template>
