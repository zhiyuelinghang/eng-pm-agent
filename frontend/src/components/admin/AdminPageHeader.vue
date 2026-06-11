<template>
  <div class="admin-page-header">
    <div class="admin-page-heading">
      <h2 class="admin-page-title">{{ title }}</h2>
      <p v-if="subtitle" class="admin-page-subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="admin-page-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<style scoped>
.admin-page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-default);
  flex-wrap: wrap;
}
.admin-page-heading { min-width: 0; }
.admin-page-title {
  font-size: 17px;
  font-weight: 650;
  color: var(--text-primary);
  margin: 0;
  line-height: 1.3;
  letter-spacing: -0.01em;
}
.admin-page-subtitle {
  font-size: 13px;
  color: var(--text-muted);
  margin: 5px 0 0;
  line-height: 1.5;
  max-width: 760px;
}
.admin-page-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
@media (max-width: 768px) {
  .admin-page-header { flex-direction: column; align-items: stretch; }
  .admin-page-actions { width: 100%; flex-wrap: wrap; }
  .admin-page-actions > * { flex: 1; }
}
</style>
