import { computed, ref, watch, type Ref } from 'vue'

export function useGroupMemberSelection(memberIds: Ref<number[]>, selectedIds: Ref<number[]>) {
  const autoSyncMembers = ref(false)
  const allParticipantsSelected = computed({
    get: () => memberIds.value.length > 0 && memberIds.value.every(id => selectedIds.value.includes(id)),
    set: (checked: boolean) => { selectedIds.value = checked ? [...memberIds.value] : [] },
  })
  const someParticipantsSelected = computed(() => (
    !allParticipantsSelected.value && memberIds.value.some(id => selectedIds.value.includes(id))
  ))
  const allGroupMembers = computed(() => allParticipantsSelected.value && autoSyncMembers.value)

  // Removing anyone makes this a manually managed group again.
  watch(allParticipantsSelected, selected => {
    if (!selected) autoSyncMembers.value = false
  }, { flush: 'sync' })

  return { autoSyncMembers, allParticipantsSelected, someParticipantsSelected, allGroupMembers }
}
