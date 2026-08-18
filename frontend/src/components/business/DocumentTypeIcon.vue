<template>
  <img class="document-type-icon" :src="iconSource" alt="" aria-hidden="true">
</template>

<script setup lang="ts">
import { computed } from 'vue'
import archiveIcon from '@/assets/document-types/archive.png'
import audioIcon from '@/assets/document-types/audio.png'
import codeIcon from '@/assets/document-types/code.png'
import documentIcon from '@/assets/document-types/docx.png'
import genericIcon from '@/assets/document-types/generic.png'
import imageIcon from '@/assets/document-types/image.png'
import pdfIcon from '@/assets/document-types/pdf.png'
import presentationIcon from '@/assets/document-types/pptx.png'
import videoIcon from '@/assets/document-types/video.png'
import spreadsheetIcon from '@/assets/document-types/xlsx.png'

type DocumentTypeIconKind =
  | 'pdf'
  | 'document'
  | 'spreadsheet'
  | 'presentation'
  | 'image'
  | 'archive'
  | 'audio'
  | 'video'
  | 'code'
  | 'generic'

const props = withDefaults(defineProps<{ kind?: DocumentTypeIconKind }>(), {
  kind: 'generic',
})

const iconSources: Record<DocumentTypeIconKind, string> = {
  pdf: pdfIcon,
  document: documentIcon,
  spreadsheet: spreadsheetIcon,
  presentation: presentationIcon,
  image: imageIcon,
  archive: archiveIcon,
  audio: audioIcon,
  video: videoIcon,
  code: codeIcon,
  generic: genericIcon,
}

const iconSource = computed(() => iconSources[props.kind])
</script>

<style scoped>
.document-type-icon {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
  pointer-events: none;
  user-select: none;
}
</style>
