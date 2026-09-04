<template>
  <section
    :class="['chat-composer-surface', { 'is-contained': contained, 'is-busy': busy }]"
    :aria-busy="busy"
  >
    <div v-if="$slots.attachments" class="chat-composer-attachments">
      <slot name="attachments" />
    </div>
    <div class="chat-composer-editor">
      <slot />
    </div>
    <footer class="chat-composer-toolbar">
      <div class="chat-composer-tools"><slot name="tools" /></div>
      <span v-if="hint" class="chat-composer-hint">{{ hint }}</span>
      <div class="chat-composer-primary"><slot name="action" /></div>
    </footer>
  </section>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  hint?: string
  contained?: boolean
  busy?: boolean
}>(), {
  hint: 'Enter 发送 · Shift + Enter 换行',
  contained: false,
  busy: false,
})
</script>

<style scoped>
.chat-composer-surface {
  display: grid;
  width: 100%;
  min-width: 0;
  gap: 0;
  padding: 9px;
  border: 1px solid rgba(28, 69, 68, 0.17);
  border-radius: 17px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow:
    0 18px 42px rgba(21, 60, 58, 0.1),
    0 1px 0 rgba(255, 255, 255, 0.92) inset;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.chat-composer-surface.is-contained {
  width: min(820px, 100%);
  margin-inline: auto;
}

.chat-composer-surface:focus-within {
  border-color: rgba(15, 118, 110, 0.55);
  box-shadow:
    0 20px 48px rgba(15, 82, 77, 0.14),
    0 0 0 3px rgba(15, 118, 110, 0.08);
}

.chat-composer-surface.is-busy {
  border-color: rgba(74, 98, 95, 0.3);
}

.chat-composer-attachments {
  min-width: 0;
  padding: 2px 4px 6px;
}

.chat-composer-editor {
  min-width: 0;
}

.chat-composer-editor :deep(.chat-composer-input) {
  display: block;
  box-sizing: border-box;
  width: 100%;
  min-height: 56px;
  max-height: 170px;
  overflow-y: auto;
  padding: 10px 10px 12px;
  border: 0;
  border-radius: 0;
  outline: 0;
  color: #18383a;
  font: inherit;
  font-size: 14px;
  line-height: 1.6;
  resize: none;
  field-sizing: content;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  background: transparent;
  box-shadow: none;
}

.chat-composer-editor :deep(textarea.chat-composer-input:focus) {
  border-color: transparent;
  outline: 0;
  box-shadow: none;
}

.chat-composer-editor :deep(textarea.chat-composer-input::placeholder),
.chat-composer-editor :deep(.chat-composer-input[data-empty='true']::before) {
  color: #8a9b9d;
}

.chat-composer-editor :deep(.chat-composer-input[data-empty='true']::before) {
  content: attr(data-placeholder);
  pointer-events: none;
}

.chat-composer-editor :deep(.chat-composer-input:disabled),
.chat-composer-editor :deep(.chat-composer-input.disabled) {
  cursor: not-allowed;
  opacity: 0.66;
}

.chat-composer-toolbar {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 2px;
}

.chat-composer-tools {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 3px;
}

.chat-composer-hint {
  overflow: hidden;
  color: #8a9899;
  font-size: 12px;
  line-height: 1.3;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-composer-primary {
  display: flex;
  justify-content: flex-end;
}

.chat-composer-tools :deep(.chat-composer-tool) {
  display: inline-flex;
  min-width: 0;
  height: 34px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 10px;
  border: 0;
  border-radius: 9px;
  color: #476561;
  font: inherit;
  font-size: 12px;
  font-weight: 650;
  background: transparent;
  cursor: pointer;
  transition: color 0.18s ease, background 0.18s ease, transform 0.18s ease;
}

.chat-composer-tools :deep(.chat-composer-tool:hover:not(:disabled)),
.chat-composer-tools :deep(.chat-composer-tool[aria-expanded='true']) {
  color: #0d6f67;
  background: #edf6f3;
}

.chat-composer-tools :deep(.chat-composer-tool:active:not(:disabled)) {
  transform: scale(0.97);
}

.chat-composer-tools :deep(.chat-composer-tool:focus-visible),
.chat-composer-tools :deep(label.chat-composer-tool:focus-within) {
  outline: 2px solid rgba(15, 118, 110, 0.36);
  outline-offset: 1px;
}

.chat-composer-tools :deep(.chat-composer-tool:disabled) {
  opacity: 0.48;
  cursor: not-allowed;
}

.chat-composer-tools :deep(.chat-composer-tool input[type='file']) {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
}

.chat-composer-primary :deep(.chat-composer-action) {
  display: inline-flex;
  min-width: 78px;
  height: 36px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 14px;
  border: 1px solid #0f766e;
  border-radius: 10px;
  color: #fff;
  font: inherit;
  font-size: 13px;
  font-weight: 720;
  background: #0f766e;
  box-shadow: 0 8px 18px rgba(15, 118, 110, 0.2);
  cursor: pointer;
  transition: transform 0.18s ease, background 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}

.chat-composer-primary :deep(.chat-composer-action:hover:not(:disabled)) {
  transform: translateY(-1px);
  border-color: #0a625b;
  background: #0a625b;
  box-shadow: 0 10px 22px rgba(15, 118, 110, 0.25);
}

.chat-composer-primary :deep(.chat-composer-action:active:not(:disabled)) {
  transform: scale(0.98);
}

.chat-composer-primary :deep(.chat-composer-action:focus-visible) {
  outline: 3px solid rgba(15, 118, 110, 0.22);
  outline-offset: 2px;
}

.chat-composer-primary :deep(.chat-composer-action:disabled) {
  border-color: #dce6e3;
  color: #93a39f;
  background: #e7eeec;
  box-shadow: none;
  cursor: not-allowed;
}

.chat-composer-primary :deep(.chat-composer-action.is-stop) {
  border-color: #4a625f;
  background: #4a625f;
  box-shadow: 0 8px 18px rgba(39, 68, 64, 0.17);
}

.chat-composer-attachments :deep(.chat-composer-files) {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  gap: 7px;
}

.chat-composer-attachments :deep(.chat-composer-file) {
  display: grid;
  min-width: 0;
  max-width: min(100%, 320px);
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 6px;
  padding: 6px 7px 6px 9px;
  border: 1px solid rgba(15, 118, 110, 0.16);
  border-radius: 9px;
  color: #284f4c;
  background: #f0f7f5;
}

.chat-composer-attachments :deep(.chat-composer-file b),
.chat-composer-attachments :deep(.chat-composer-file strong) {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-composer-attachments :deep(.chat-composer-file small) {
  color: #667a76;
  font-size: 12px;
  line-height: 1.4;
  white-space: nowrap;
}

.chat-composer-attachments :deep(.chat-composer-file-remove) {
  display: inline-grid;
  width: 24px;
  height: 24px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 6px;
  color: #6c7f7b;
  font: inherit;
  font-size: 16px;
  line-height: 1;
  background: transparent;
  cursor: pointer;
}

.chat-composer-attachments :deep(.chat-composer-file-remove:hover) {
  color: #a94327;
  background: #f9ece7;
}

@media (max-width: 680px) {
  .chat-composer-surface {
    border-radius: 14px;
  }

  .chat-composer-toolbar {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .chat-composer-hint {
    display: none;
  }
}

@media (max-width: 420px) {
  .chat-composer-tools :deep(.chat-composer-tool) {
    padding-inline: 8px;
  }

  .chat-composer-primary :deep(.chat-composer-action) {
    min-width: 70px;
    padding-inline: 11px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .chat-composer-surface,
  .chat-composer-tools :deep(.chat-composer-tool),
  .chat-composer-primary :deep(.chat-composer-action) {
    transition: none;
  }
}
</style>
