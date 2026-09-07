import { nextTick, ref, type Ref } from 'vue'

export type ProjectChatMentionOption = {
  key: string
  type: 'all' | 'user' | 'agent'
  id: number | string
  name: string
  subtitle: string
}

type ComposerOptions = {
  draft: Ref<string>
  filteredMentionOptions: () => ProjectChatMentionOption[]
  loadMentionAgents: () => Promise<void>
  sendMessage: () => Promise<void>
  warn: (message: string) => void
}

const COMPOSER_MAX_LENGTH = 20000

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export function useProjectChatComposer(options: ComposerOptions) {
  const composerInput = ref<HTMLDivElement | null>(null)
  const mentionMenuOpen = ref(false)
  const mentionQuery = ref('')
  const mentionRangeStart = ref(0)
  const mentionRangeEnd = ref(0)
  const mentionActiveIndex = ref(0)
  const selectedMentions = ref<ProjectChatMentionOption[]>([])

  function composerCaretOffset() {
    const editor = composerInput.value
    const selection = window.getSelection()
    if (!editor || !selection?.rangeCount) return options.draft.value.length
    const range = selection.getRangeAt(0)
    if (!editor.contains(range.commonAncestorContainer)) return options.draft.value.length
    const beforeCaret = range.cloneRange()
    beforeCaret.selectNodeContents(editor)
    beforeCaret.setEnd(range.endContainer, range.endOffset)
    return beforeCaret.toString().length
  }

  function setComposerCaretOffset(requestedOffset: number) {
    const editor = composerInput.value
    if (!editor) return
    const selection = window.getSelection()
    if (!selection) return
    const offset = Math.max(0, Math.min(requestedOffset, editor.textContent?.length || 0))
    const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT)
    let traversed = 0
    let textNode = walker.nextNode() as Text | null
    const range = document.createRange()
    while (textNode) {
      const nextOffset = traversed + textNode.data.length
      if (offset <= nextOffset) {
        const mentionToken = textNode.parentElement?.closest<HTMLElement>('[data-mention-key]')
        if (mentionToken) range.setStartAfter(mentionToken)
        else range.setStart(textNode, offset - traversed)
        range.collapse(true)
        selection.removeAllRanges()
        selection.addRange(range)
        return
      }
      traversed = nextOffset
      textNode = walker.nextNode() as Text | null
    }
    range.selectNodeContents(editor)
    range.collapse(false)
    selection.removeAllRanges()
    selection.addRange(range)
  }

  function composerMentionAtOffset(offset: number) {
    const editor = composerInput.value
    if (!editor) return false
    let traversed = 0
    return [...editor.childNodes].some(node => {
      const length = node.textContent?.length || 0
      const isMention = node instanceof HTMLElement && Boolean(node.dataset.mentionKey)
      const containsOffset = isMention && offset >= traversed && offset <= traversed + length
      traversed += length
      return containsOffset
    })
  }

  function syncSelectedMentionsFromEditor() {
    const editor = composerInput.value
    if (!editor) return
    const liveKeys = new Set(
      [...editor.querySelectorAll<HTMLElement>('[data-mention-key]')]
        .map(node => node.dataset.mentionKey)
        .filter((key): key is string => Boolean(key)),
    )
    selectedMentions.value = selectedMentions.value.filter(mention => liveKeys.has(mention.key))
  }

  function renderComposer(caretOffset = options.draft.value.length) {
    const editor = composerInput.value
    if (!editor) return
    const mentionsByToken = new Map<string, ProjectChatMentionOption>()
    selectedMentions.value.forEach(mention => {
      mentionsByToken.set(`@${mention.name}`, mention)
    })
    const tokens = [...mentionsByToken.keys()].sort((left, right) => right.length - left.length)
    const parts = tokens.length
      ? options.draft.value.split(new RegExp(`(${tokens.map(escapeRegExp).join('|')})`, 'g')).filter(Boolean)
      : [options.draft.value]
    const fragment = document.createDocumentFragment()
    parts.forEach(part => {
      const mention = mentionsByToken.get(part)
      if (!mention) {
        fragment.appendChild(document.createTextNode(part))
        return
      }
      const token = document.createElement('span')
      token.className = `composer-mention ${mention.type}`
      token.contentEditable = 'false'
      token.dataset.mentionKey = mention.key
      token.textContent = part
      fragment.appendChild(token)
    })
    editor.replaceChildren(fragment)
    setComposerCaretOffset(caretOffset)
  }

  function syncDraftFromEditor() {
    const editor = composerInput.value
    if (!editor) return
    const caret = composerCaretOffset()
    const content = (editor.textContent || '').replace(/\r/g, '')
    options.draft.value = content.slice(0, COMPOSER_MAX_LENGTH)
    syncSelectedMentionsFromEditor()
    if (content.length > COMPOSER_MAX_LENGTH) {
      renderComposer(Math.min(caret, COMPOSER_MAX_LENGTH))
    }
  }

  function closeMentionMenu() {
    mentionMenuOpen.value = false
    mentionQuery.value = ''
    mentionActiveIndex.value = 0
  }

  function clearComposer() {
    options.draft.value = ''
    selectedMentions.value = []
    composerInput.value?.replaceChildren()
    closeMentionMenu()
  }

  function deferCloseMentionMenu() {
    window.setTimeout(() => closeMentionMenu(), 120)
  }

  function updateMentionState() {
    syncDraftFromEditor()
    const input = composerInput.value
    if (!input) return closeMentionMenu()
    const caret = composerCaretOffset()
    if (composerMentionAtOffset(caret)) return closeMentionMenu()
    const beforeCaret = options.draft.value.slice(0, caret)
    const atIndex = beforeCaret.lastIndexOf('@')
    if (atIndex < 0) return closeMentionMenu()
    const query = beforeCaret.slice(atIndex + 1)
    if (/\s/.test(query) || query.length > 40) return closeMentionMenu()
    mentionRangeStart.value = atIndex
    mentionRangeEnd.value = caret
    if (mentionQuery.value !== query) mentionActiveIndex.value = 0
    mentionQuery.value = query
    mentionMenuOpen.value = true
    void options.loadMentionAgents()
  }

  async function selectMention(option: ProjectChatMentionOption) {
    if (
      option.type === 'agent'
      && selectedMentions.value.some(item => item.type === 'agent' && item.key !== option.key)
    ) {
      options.warn('每条消息最多只能提及一个智能体。')
      closeMentionMenu()
      return
    }
    const before = options.draft.value.slice(0, mentionRangeStart.value)
    const after = options.draft.value.slice(mentionRangeEnd.value)
    const inserted = `@${option.name} `
    options.draft.value = `${before}${inserted}${after}`
    if (!selectedMentions.value.some(item => item.key === option.key)) {
      selectedMentions.value = [...selectedMentions.value, option]
    }
    const caret = before.length + inserted.length
    closeMentionMenu()
    await nextTick()
    composerInput.value?.focus()
    renderComposer(caret)
  }

  function insertComposerText(value: string) {
    const editor = composerInput.value
    const selection = window.getSelection()
    if (!editor || !selection) return
    let range: Range
    if (selection.rangeCount && editor.contains(selection.getRangeAt(0).commonAncestorContainer)) {
      range = selection.getRangeAt(0)
    } else {
      range = document.createRange()
      range.selectNodeContents(editor)
      range.collapse(false)
    }
    const currentLength = editor.textContent?.length || 0
    const availableLength = Math.max(
      0,
      COMPOSER_MAX_LENGTH - currentLength + range.toString().length,
    )
    const safeValue = value.slice(0, availableLength)
    range.deleteContents()
    const textNode = document.createTextNode(safeValue)
    range.insertNode(textNode)
    range.setStartAfter(textNode)
    range.collapse(true)
    selection.removeAllRanges()
    selection.addRange(range)
    updateMentionState()
  }

  function openMentionMenu() {
    const input = composerInput.value
    if (!input) return
    input.focus()
    insertComposerText('@')
  }

  function handleComposerPaste(event: ClipboardEvent) {
    event.preventDefault()
    insertComposerText(event.clipboardData?.getData('text/plain').replace(/\r\n?/g, '\n') || '')
  }

  function handleComposerKeydown(event: KeyboardEvent) {
    if (event.isComposing) return
    const filtered = options.filteredMentionOptions()
    if (mentionMenuOpen.value) {
      if (event.key === 'ArrowDown') {
        event.preventDefault()
        mentionActiveIndex.value = Math.min(
          mentionActiveIndex.value + 1,
          Math.max(0, filtered.length - 1),
        )
        return
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault()
        mentionActiveIndex.value = Math.max(mentionActiveIndex.value - 1, 0)
        return
      }
      if (
        ((event.key === 'Enter' && !event.shiftKey) || event.key === 'Tab')
        && filtered.length
      ) {
        event.preventDefault()
        void selectMention(filtered[mentionActiveIndex.value])
        return
      }
      if (event.key === 'Escape') {
        event.preventDefault()
        closeMentionMenu()
        return
      }
    }
    if (event.key === 'Enter' && event.shiftKey) {
      event.preventDefault()
      insertComposerText('\n')
      return
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void options.sendMessage()
    }
  }

  return {
    composerInput,
    mentionMenuOpen,
    mentionQuery,
    mentionActiveIndex,
    selectedMentions,
    renderComposer,
    syncDraftFromEditor,
    clearComposer,
    closeMentionMenu,
    deferCloseMentionMenu,
    updateMentionState,
    selectMention,
    openMentionMenu,
    handleComposerPaste,
    handleComposerKeydown,
  }
}
