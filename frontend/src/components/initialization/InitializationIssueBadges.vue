<template>
  <span v-if="issues.length" class="initialization-issue-badges">
    <button
      type="button"
      :class="summaryLevel"
      :title="summaryTitle"
      @click.stop="$emit('select', issues)"
    >
      {{ summaryLabel }}
    </button>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

export type InitializationIssueBadgeItem = {
  id: number
  level: 'error' | 'warning'
  label: string
  title: string
}

const props = defineProps<{ issues: InitializationIssueBadgeItem[] }>()
defineEmits<{ select: [issues: InitializationIssueBadgeItem[]] }>()

const summaryLevel = computed(() => (
  props.issues.some(issue => issue.level === 'error') ? 'error' : 'warning'
))
const summaryLabel = computed(() => (
  props.issues.length > 1 ? `${props.issues.length} 项问题` : props.issues[0]?.label || '查看问题'
))
const summaryTitle = computed(() => (
  props.issues.length > 1
    ? `查看 ${props.issues.length} 项核验问题`
    : props.issues[0]?.title || '查看核验问题'
))
</script>

<style scoped>
.initialization-issue-badges {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  margin-left: 6px;
  vertical-align: middle;
}

.initialization-issue-badges button {
  min-height: 24px;
  border: 1px solid;
  border-radius: 999px;
  padding: 2px 8px;
  font: inherit;
  font-size: 12px;
  font-weight: 750;
  line-height: 18px;
  white-space: nowrap;
  cursor: pointer;
}

.initialization-issue-badges button.error {
  border-color: #e9b8ab;
  color: #9a3f2a;
  background: #fff1ed;
}

.initialization-issue-badges button.warning {
  border-color: #e7d29f;
  color: #805c16;
  background: #fff8e8;
}

.initialization-issue-badges button:hover,
.initialization-issue-badges button:focus-visible {
  filter: brightness(.97);
  outline: 2px solid rgba(25, 116, 100, .24);
  outline-offset: 1px;
}
</style>
