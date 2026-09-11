<template>
  <div v-if="issues.length" class="field-issues" aria-label="字段核验问题">
    <div v-for="(issue, index) in issues" :key="index" class="field-issue" :class="issue.level">
      <span class="issue-level">{{ issue.level === 'error' ? '需修正' : '需核对' }}</span>
      <span class="issue-title">{{ issue.title }}</span>
      <p>{{ issue.message }}</p>
      <p v-if="issue.suggestion" class="issue-suggestion">{{ issue.suggestion }}</p>
      <p v-if="issue.level === 'error'" class="issue-suggestion">请修改原始资料后重新上传，核验通过后才能入库。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { InitializationChangeIssue } from '@/types/initializationChanges'
defineProps<{ issues: InitializationChangeIssue[] }>()
</script>

<style scoped>
.field-issues { display:grid; gap:7px; flex-basis:100%; min-width:0; margin-top:5px; }
.field-issue { padding:7px 9px; border-left:2px solid var(--color-warning); border-radius:3px; background:var(--color-warning-soft); color:var(--text-primary); font-size:12px; line-height:1.65; }
.field-issue.error { border-color:var(--color-danger); background:var(--color-danger-soft); }
.issue-level { color:var(--color-warning); font-weight:600; }.error .issue-level { color:var(--color-danger); }
.issue-title { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); }
p { margin:3px 0 0; overflow-wrap:anywhere; white-space:normal; font-weight:400; }.issue-suggestion { color:var(--text-secondary); }
</style>
