<script setup lang="ts">
import type { DocType } from '../types'

const props = defineProps<{
  type: DocType | string
}>()

const typeColors: Record<string, string> = {
  note: 'bg-type-note',
  insight: 'bg-type-insight',
  commit: 'bg-type-commit',
  initiative: 'bg-type-initiative',
  code: 'bg-type-code',
}

const typeLabels: Record<string, string> = {
  note: 'Note',
  insight: 'Insight',
  commit: 'Commit',
  initiative: 'Initiative',
  code: 'Code',
}
</script>

<template>
  <span
    :class="[
      'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium text-white',
      typeColors[props.type] || 'bg-gray-600',
    ]"
  >
    {{ typeLabels[props.type] || props.type }}
  </span>
</template>
